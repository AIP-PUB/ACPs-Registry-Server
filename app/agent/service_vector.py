from typing import List, Optional
import json
import logging

from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams, PointStruct
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings
from app.agent.model import Agent
from app.agent.exception import AgentException, AgentError

# Initialize OpenAI client with API key - 在模块级别初始化
llm_client = None
try:
    llm_client = OpenAI(
        api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_API_BASE_URL
    )
    logging.info("OpenAI client initialized successfully")
except Exception as e:
    logging.error(f"Failed to initialize OpenAI client: {e}")

# Initialize Qdrant client only if enabled
qdrant_client = None
if settings.QDRANT_ENABLED:
    try:
        qdrant_client = QdrantClient(
            url=settings.QDRANT_URL,
            timeout=10.0,  # Set explicit timeout
            prefer_grpc=False,  # Use HTTP instead of gRPC for more reliable connections
        )

        # Check if collection exists first
        collections = qdrant_client.get_collections().collections
        collection_names = [collection.name for collection in collections]

        # Create collection only if it doesn't exist
        if settings.QDRANT_COLLECTION not in collection_names:
            qdrant_client.create_collection(
                collection_name=settings.QDRANT_COLLECTION,
                vectors_config=VectorParams(size=2048, distance=Distance.COSINE),
            )
            logging.info(f"Created Qdrant collection: {settings.QDRANT_COLLECTION}")
        logging.info("Qdrant client initialized successfully")
    except Exception as e:
        logging.error(f"Failed to initialize Qdrant client: {e}")
        # Continue without vector search in development - make client None
        qdrant_client = None
else:
    logging.info(
        "Qdrant is disabled (QDRANT_ENABLED=false), skipping client initialization"
    )


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def generate_embeddings(text: str) -> List[float]:
    """
    Generate embeddings for text using OpenAI's API
    """
    if not llm_client:
        logging.error("OpenAI client is not initialized")
        raise AgentException(
            status_code=500,
            error_name=AgentError.LLM_CLIENT_NOT_INITIALIZED,
            error_msg="OpenAI client is not initialized",
        )

    try:
        logging.error(f"Using OpenAI model: {settings.OPENAI_MODEL}")
        # 使用模块级别初始化的客户端
        response = llm_client.embeddings.create(model=settings.OPENAI_MODEL, input=text)
        if not response.data or len(response.data) == 0:
            logging.error("No embeddings returned from OpenAI API")
            raise AgentException(
                status_code=500,
                error_name=AgentError.INVALID_EMBEDDING_RESPONSE,
                error_msg="No embeddings returned from OpenAI API",
            )
        if not response.data[0].embedding:
            logging.error("Empty embedding returned from OpenAI API")
            raise AgentException(
                status_code=500,
                error_name=AgentError.INVALID_EMBEDDING_RESPONSE,
                error_msg="Empty embedding returned from OpenAI API",
            )
        # Check if the embedding is a list of floats
        if not isinstance(response.data[0].embedding, list):
            logging.error("Embedding is not a list")
            raise AgentException(
                status_code=500,
                error_name=AgentError.INVALID_EMBEDDING_RESPONSE,
                error_msg="Embedding is not a list",
            )
        if not all(isinstance(x, float) for x in response.data[0].embedding):
            logging.error("Embedding contains non-float values")
            raise AgentException(
                status_code=500,
                error_name=AgentError.INVALID_EMBEDDING_RESPONSE,
                error_msg="Embedding contains non-float values",
            )
        return response.data[0].embedding
    except AgentException:
        # Re-raise AgentException without wrapping it
        raise
    except Exception as e:
        logging.error(f"Error generating embeddings: {e}")
        raise AgentException(
            status_code=500,
            error_name=AgentError.EMBEDDING_GENERATION_FAILED,
            error_msg=f"Error generating embeddings: {str(e)}",
        )


def get_agent_embedding_text(agent: Agent) -> str:
    """
    Create a text representation of an agent for embedding
    """
    # Combine relevant agent fields for semantic search
    text_parts = [
        f"Agent Name: {agent.name}",
        f"Version: {agent.version}",
        f"Description: {agent.description or ''}",
    ]

    # Add capabilities
    try:
        capabilities = json.loads(agent.capabilities_json)

        # Add each capability field that's important for search
        if isinstance(capabilities, dict):
            for key, value in capabilities.items():
                if isinstance(value, (str, int, float, bool)):
                    text_parts.append(f"{key}: {value}")
                elif isinstance(value, list) and all(isinstance(x, str) for x in value):
                    text_parts.append(f"{key}: {', '.join(value)}")
    except:
        pass

    return " ".join(text_parts)


def index_agent(agent: Agent) -> Optional[str]:
    """
    Index an agent in the vector database for semantic search
    Returns the point ID if successful
    """
    # Check if Qdrant is enabled
    if not settings.QDRANT_ENABLED:
        logging.info(
            f"QDRANT_ENABLED is false, skipping vector indexing for agent {agent.id}"
        )
        return f"mock_vector_{agent.id}"

    if not qdrant_client:
        logging.error("Qdrant client is not initialized")
        raise AgentException(
            status_code=500,
            error_name=AgentError.VECTOR_CLIENT_NOT_INITIALIZED,
            error_msg="Qdrant client is not initialized",
        )

    try:
        # Generate text for embedding
        text = get_agent_embedding_text(agent)

        # Generate embeddings
        embeddings = generate_embeddings(text)

        # Use agent ID as point ID
        point_id = str(agent.id)

        # Create payload with agent metadata
        payload = {
            "agent_id": str(agent.id),
        }

        # Upsert the point in Qdrant
        qdrant_client.upsert(
            collection_name=settings.QDRANT_COLLECTION,
            points=[PointStruct(id=point_id, vector=embeddings, payload=payload)],
        )

        return point_id
    except AgentException:
        # Re-raise AgentException without wrapping it
        raise
    except Exception as e:
        logging.error(f"Error indexing agent: {e}")
        raise AgentException(
            status_code=500,
            error_name=AgentError.VECTOR_INDEX_FAILED,
            error_msg=f"Error indexing agent: {str(e)}",
            input_params={"agent_id": str(agent.id)},
        )


def search_agents_by_vector(
    query: str, page_size: int = 5, page_num: int = 1
) -> List[str]:
    """
    Search for agents using vector similarity
    Returns a list of agent IDs sorted by relevance

    Args:
        query: The search query string
        page_size: Number of results per page
        page_num: Page number (starting from 1)

    Returns:
        List of agent IDs sorted by relevance
    """
    # Check if Qdrant is enabled
    if not settings.QDRANT_ENABLED:
        logging.info("QDRANT_ENABLED is false, returning empty search results")
        return []

    if not qdrant_client:
        logging.error("Qdrant client is not initialized")
        return []

    try:
        # Generate embeddings for the query
        query_embeddings = generate_embeddings(query)

        # Calculate the total number of results to fetch
        # We need to get enough results to cover all pages up to the requested one
        total_limit = page_size * page_num

        # Search for similar vectors in Qdrant
        search_results = qdrant_client.search(
            collection_name=settings.QDRANT_COLLECTION,
            query_vector=query_embeddings,
            limit=total_limit,
        )

        # Extract agent IDs from search results
        agent_ids = [hit.payload.get("agent_id") for hit in search_results]

        # Calculate the start and end indices for the requested page
        start_idx = (page_num - 1) * page_size
        end_idx = start_idx + page_size

        # Return only the IDs for the requested page
        return agent_ids[start_idx:end_idx]
    except AgentException:
        # Re-raise AgentException without wrapping it
        raise
    except Exception as e:
        logging.error(f"Error searching agents: {e}")
        raise AgentException(
            status_code=500,
            error_name=AgentError.VECTOR_SEARCH_FAILED,
            error_msg=f"Error searching agents: {str(e)}",
            input_params={"query": query},
        )


def delete_agent_from_vector(point_id: str) -> bool:
    """
    Delete an agent from the vector database
    """
    # Check if Qdrant is enabled
    if not settings.QDRANT_ENABLED:
        logging.info(
            f"QDRANT_ENABLED is false, skipping vector deletion for point {point_id}"
        )
        return True

    if not qdrant_client:
        logging.error("Qdrant client is not initialized")
        return False

    try:
        qdrant_client.delete(
            collection_name=settings.QDRANT_COLLECTION, points_selector=[point_id]
        )
        return True
    except Exception as e:
        logging.error(f"Error deleting agent from vector database: {e}")
        raise AgentException(
            status_code=500,
            error_name=AgentError.VECTOR_DELETE_FAILED,
            error_msg=f"Error deleting agent from vector database: {str(e)}",
            input_params={"point_id": point_id},
        )
