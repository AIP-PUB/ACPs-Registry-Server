import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime
from app.agent.service import update_agent_acs_data
from app.agent.model import Agent


class TestUpdateAgentAcsData:
    def test_update_agent_acs_data_updates_aic_and_reassigns_acs(self):
        """
        Test that update_agent_acs_data updates the AIC in ACS and re-assigns the ACS dictionary
        to the agent object to ensure SQLAlchemy detects the change.
        """
        # Setup
        initial_acs = {"name": "Test Agent", "version": "1.0.0", "active": True}

        # Create a mock agent
        agent = MagicMock(spec=Agent)
        agent.acs = initial_acs
        agent.aic = "test-aic-123"
        agent.is_active = True

        # Mock db session
        db = MagicMock()

        # Mock get_beijing_time to return a fixed time
        fixed_time = datetime(2023, 1, 1, 12, 0, 0)

        with patch("app.agent.service.get_beijing_time", return_value=fixed_time):
            with patch("app.sync.service.update_agent_with_changelog") as mock_sync:
                # Execute
                update_agent_acs_data(agent, db)

                # Verify
                # 1. Check that AIC was added to ACS
                assert agent.acs["aic"] == "test-aic-123"

                # 2. Check that lastModifiedTime was added
                assert agent.acs["lastModifiedTime"] == fixed_time.isoformat()

                # 3. CRITICAL: Check that agent.acs is NOT the same object as initial_acs
                # This confirms that a copy was made and assigned back
                assert agent.acs is not initial_acs

                # 4. Check that sync function was called
                mock_sync.assert_called_once()

    def test_update_agent_acs_data_no_change(self):
        """
        Test that if there are no changes, ACS is not modified and sync is not called.
        """
        # Setup
        fixed_time = datetime(2023, 1, 1, 12, 0, 0)
        initial_acs = {
            "name": "Test Agent",
            "version": "1.0.0",
            "active": True,
            "aic": "test-aic-123",
            "lastModifiedTime": fixed_time.isoformat(),
        }

        agent = MagicMock(spec=Agent)
        agent.acs = initial_acs
        agent.aic = "test-aic-123"
        agent.is_active = True

        db = MagicMock()

        with patch("app.agent.service.get_beijing_time", return_value=fixed_time):
            with patch("app.sync.service.update_agent_with_changelog") as mock_sync:
                # Execute
                update_agent_acs_data(agent, db)

                # Verify
                mock_sync.assert_not_called()

                # If no change, agent.acs should be the same object
                assert agent.acs is initial_acs

    def test_update_agent_acs_data_active_status_change(self):
        """
        Test that changing active status updates ACS.
        """
        # Setup
        initial_acs = {
            "name": "Test Agent",
            "version": "1.0.0",
            "active": True,
            "aic": "test-aic-123",
        }

        agent = MagicMock(spec=Agent)
        agent.acs = initial_acs
        agent.aic = "test-aic-123"
        agent.is_active = False  # Changed to False

        db = MagicMock()

        with patch("app.agent.service.get_beijing_time") as mock_time:
            mock_time.return_value = datetime.now()
            with patch("app.sync.service.update_agent_with_changelog") as mock_sync:
                # Execute
                update_agent_acs_data(agent, db)

                # Verify
                assert agent.acs["active"] is False
                assert agent.acs is not initial_acs
                mock_sync.assert_called_once()
