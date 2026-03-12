import pytest
from unittest.mock import patch
from app.utils import aic


@pytest.mark.unit
class TestAICSpecV02:
    def test_crc16_example_from_spec(self):
        body_1_9 = "1.2.156.1234.1.34C2.478BDF.3GF546.1"
        with patch("app.utils.aic.AIC_CRC_SALT", ""):
            assert aic.calculate_aic_checksum(body_1_9) == "1EAI"

    def test_validate_example_from_spec(self):
        full = "1.2.156.1234.1.34C2.478BDF.3GF546.1.1EAI"
        with patch("app.utils.aic.AIC_CRC_SALT", ""):
            assert aic.validate_aic(full, expected_prefix="1.2.156.1234") is True
            # 大小写/空白容忍
            assert aic.validate_aic("  " + full.lower() + "\n", expected_prefix="1.2.156.1234") is True

    def test_generate_entity_aic(self):
        code = aic.generate_aic()
        assert aic.validate_aic(code) is True
        assert aic.is_entity_aic(code) is True
        assert aic.is_ontology_aic(code) is False
        assert aic.get_instance_serial(code) is not None

    def test_generate_ontology_aic(self):
        code = aic.generate_ontology_aic()
        assert aic.validate_aic(code) is True
        assert aic.is_ontology_aic(code) is True
        assert aic.is_entity_aic(code) is False
        instance = aic.get_instance_serial(code)
        assert instance is not None
        assert set(instance) == {"0"}

    def test_get_ontology_from_entity(self):
        entity = aic.generate_aic()
        onto = aic.get_ontology_aic_from_entity(entity)
        assert onto is not None
        assert aic.validate_aic(onto) is True
        assert aic.is_ontology_aic(onto) is True
        # 1~7/9 级保持一致
        e_parts = entity.split(".")
        o_parts = onto.split(".")
        assert e_parts[:7] == o_parts[:7]
        assert e_parts[8] == o_parts[8]

    def test_generate_entity_from_ontology(self):
        onto = aic.generate_ontology_aic()
        entity = aic.generate_entity_aic_from_ontology(onto)
        assert entity is not None
        assert aic.validate_aic(entity) is True
        assert aic.is_entity_aic(entity) is True
        # 1~7/9 级保持一致
        o_parts = onto.split(".")
        e_parts = entity.split(".")
        assert o_parts[:7] == e_parts[:7]
        assert o_parts[8] == e_parts[8]

    def test_derived_entity_like_prefix(self):
        onto = aic.generate_ontology_aic()
        prefix = aic.get_derived_entity_like_prefix(onto)
        assert prefix is not None
        entity = aic.generate_entity_aic_from_ontology(onto)
        assert entity is not None
        assert entity.startswith(prefix)


@pytest.mark.unit
class TestAICInvalidInputs:
    def test_invalid_prefix_or_segments(self):
        assert aic.validate_aic("") is False
        assert aic.validate_aic("1.2.156.1234") is False
        # bad checksum
        assert aic.validate_aic("1.2.156.1234.1.1.AAAAAA.1.1.1.0000") is False

    def test_generate_invalid_custom_codes(self):
        with pytest.raises(ValueError):
            aic.generate_aic(protocol_version="")
        with pytest.raises(ValueError):
            aic.generate_aic(protocol_version="12")
        with pytest.raises(ValueError):
            aic.generate_aic(manager_code="00*1")
        with pytest.raises(ValueError):
            aic.generate_aic(provider_code="")
