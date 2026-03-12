import requests
import json
import logging
from app.agent.exception import AgentException, AgentError
from fastapi import status
from jsonschema import validate as jsonValidate, ValidationError
import os
from urllib.parse import urlparse

from app.core.config import settings
logger = logging.getLogger(__name__)


def is_url_reachable(url, expected_status_code=None):
    try:
        response = requests.get(url, timeout=5)
        
        if expected_status_code is None:
            # If no specific status code is required, any response means it's reachable
            return True
        else:
            # If a specific status code is required, check if it matches
            return response.status_code == expected_status_code
    except requests.RequestException:
        # If an exception occurs (e.g., connection error, timeout), it's not reachable
        return False
    

def check_url_format(url):
    # Basic check for URL format
    try:
        parsed_url = urlparse(url)
        if parsed_url.scheme in ["http", "https"] and parsed_url.netloc:
            return True
        else:
            return False
    except Exception as e:
        logger.info(f"URL parsing error: {url}, error: {e}")
        return False
    
    
# 检查 x-caChallengeBaseUrl 是否可达且符合要求，复合返回None，否则返回错误信息
def check_ca_challenge_base_url(url):
    ca_challenge_status_path_type = settings.CA_CHALLENGE_STATUS_PATH_TYPE
    status_url = None
    parsed_url = None
    try:
        parsed_url = urlparse(url)
        if ca_challenge_status_path_type == "root":
            status_url = f"{parsed_url.scheme}://{parsed_url.netloc}/status"
        else:
            path = parsed_url.path.rsplit('/', 2)[0]
            status_url = f"{parsed_url.scheme}://{parsed_url.netloc}{path}/status"
    except Exception as e:
        msg = f"URL parsing error: {url}, error: {e}"
        logger.info(msg)
        return False, msg
    
    try:
        response = requests.get(status_url, timeout=5)
        if (response.status_code != 200):
            msg = f"response status: {response.status_code}"
            logger.info(msg)
            return False, msg

        if not is_valid_json(response.text):
            msg = f"Invalid response: {response.text}"
            logger.info(msg)
            return False, msg
        
        response_json = json.loads(response.text)

        if response_json.get("status") != "running":
            msg = f"Invalid response: {response.text}"
            logger.info(msg)
            return False, msg
        
        if response_json.get("api_base_path").rstrip("/") != parsed_url.path.rstrip("/"):
            msg = f"different from challenge server: {response_json.get('api_base_path')}"
            logger.info(msg)
            return False, msg

        return True, None
    except requests.RequestException as e:
        msg = f"{url} is not reachable"
        logger.info(msg)
        return False, msg


def is_valid_json(json_string):
    try:
        json.loads(json_string)
        return True
    except ValueError as e:
        logger.warning(f"Invalid JSON string: {json_string}, error: {e}")
        return False
    

def validate(acs: str | dict):
    if acs is None or (isinstance(acs, str) and not is_valid_json(acs)) or (isinstance(acs, dict) and not acs):
        raise AgentException(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_name=AgentError.ACS_NOT_EXISTED,
            error_msg="ACS cannot be null",
            input_params={"acs": str(acs)},
        )

    # Locate acsSchema.json in the project root (assuming 3 levels up from app/agent/api.py)
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    schema_path = os.path.join(base_dir, "app/agent/acsSchema.json")

    if os.path.exists(schema_path):
        with open(schema_path, "r", encoding="utf-8") as f:
            schema = json.load(f)
        try:
            if isinstance(acs, str):
                instance = json.loads(acs)
            else:
                instance = acs
            jsonValidate(instance=instance, schema=schema)
        except ValidationError as e:
            logger.error(f"ACS validation error: {e.message}")
            raise AgentException(
                status_code=status.HTTP_400_BAD_REQUEST,
                error_name=AgentError.INVALID_ACS,
                error_msg=f"Json path: [ {e.json_path} ]; Error message: [ {e.message} ]",
                input_params={"acs": acs},
            )
    
    # Additional custom validations
    instance = acs if isinstance(acs, dict) else json.loads(acs)
    security_schemes = instance.get("securitySchemes")
    mTllsChallengeBaseUrls = {} # To check with endpoints later
    x_caChallenge_base_url = None
    
    # Validate security schemes
    for schema_name, schema in security_schemes.items():
        schema_type = schema.get("type")
        if schema_type == "mutualTLS":
            x_caChallenge_base_url = schema.get("x-caChallengeBaseUrl")
            # 1. must be valid URL format
            if not check_url_format(x_caChallenge_base_url):
                raise AgentException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    error_name=AgentError.INVALID_ACS,
                    error_msg=f"x-caChallengeBaseUrl format: {schema_name}",
                    input_params={"acs": acs},
                )
            # 2. must be present (checked by json schema already)
            # 3. must be reachable
            challengeBaseUrlValid, err = check_ca_challenge_base_url(x_caChallenge_base_url)
            if not challengeBaseUrlValid:
                raise AgentException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    error_name=AgentError.INVALID_ACS,
                    error_msg=f"x-caChallengeBaseUrl: {err}",
                    input_params={"acs": acs},
                )
            mTllsChallengeBaseUrl = x_caChallenge_base_url
            # Remove trailing '/' for later comparison
            if mTllsChallengeBaseUrl.endswith("/"):
                mTllsChallengeBaseUrl = mTllsChallengeBaseUrl[:-1]
            mTllsChallengeBaseUrls[schema_name] = mTllsChallengeBaseUrl

    # Validate endpoints: 
    endpoints = instance.get("endPoints")
    if endpoints:
        for endpoint in endpoints:
            # Validate endpoint: 
            # 1. must use mTLS security scheme in any of endPoint
            securities = endpoint.get("security")
            mtls_used = False
            for security in securities:
                for scr_name in security.keys():
                    if scr_name in mTllsChallengeBaseUrls.keys():
                        mtls_used = True
                        break
                if mtls_used:
                    break
            if not mtls_used:
                raise AgentException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    error_name=AgentError.INVALID_ACS,
                    error_msg=f"endPoint must use mutualTLS security scheme",
                    input_params={"acs": acs},
                )
            # 2. url is required in endpoint (checked by json schema already)
            ep_url = endpoint.get("url")
            # 3. url must be valid format
            if not check_url_format(ep_url):
                raise AgentException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    error_name=AgentError.INVALID_ACS,
                    error_msg=f"endpoint URL format: {endpoint.get('url', '')}",
                    input_params={"acs": acs},
                )
            # 4. x-caChallengeBaseUrl must not appear in any endPoint
            if ep_url.endswith("/"):
                ep_url = ep_url[:-1]
            if ep_url in mTllsChallengeBaseUrls.values():
                raise AgentException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    error_name=AgentError.INVALID_ACS,
                    error_msg=f"x-caChallengeBaseUrl must not appear in any endPoint: {ep_url}",
                    input_params={"acs": acs},
                )

    # webAppUrl validation:
    web_app_url = instance.get("webAppUrl")
    # webAppUrl and endpoints cannot both be absent
    if web_app_url is None and (endpoints is None or len(endpoints) == 0):
        raise AgentException(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_name=AgentError.INVALID_ACS,
            error_msg=f"Either webAppUrl or endpoints must be present in ACS",
            input_params={"acs": acs},
        )
