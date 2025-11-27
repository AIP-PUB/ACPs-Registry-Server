import hashlib
from datetime import datetime, timezone, timedelta

import pytest

from app.utils import aic
from app.utils.utils import BEIJING_TIMEZONE


@pytest.mark.unit
class TestBase36EncodeDecode:
    def test_base36_encode_basic_and_padding(self):
        assert aic._base36_encode(0, 3) == "000"
        assert aic._base36_encode(1, 1) == "1"
        assert aic._base36_encode(35, 1) == "Z"
        assert aic._base36_encode(36, 2) == "10"
        assert aic._base36_encode(5, 4) == "0005"
        # Known year example from docstring
        assert aic._base36_encode(2025, 3) == "1K9"

    def test_base36_encode_truncates_when_exceeds_length(self):
        # Build a number with known base36 then ensure truncation keeps lower-order digits
        # 36^4 == base36 "10000"
        num = 36**4 + aic._base36_decode("ABC")  # base36: "10000" + "ABC" -> "10000ABC"
        encoded_full = aic._base36_encode(num, 8)
        assert encoded_full.endswith("0ABC")  # sanity of composition
        # If length is 4, we should keep only the low 4 digits
        assert aic._base36_encode(num, 4) == encoded_full[-4:]

    def test_base36_encode_errors(self):
        with pytest.raises(ValueError):
            aic._base36_encode(-1, 1)
        with pytest.raises(ValueError):
            aic._base36_encode(1, 0)
        with pytest.raises(ValueError):
            aic._base36_encode(1, -5)

    def test_base36_decode_basic_and_tolerances(self):
        assert aic._base36_decode("") == 0
        assert aic._base36_decode("000") == 0
        assert aic._base36_decode("Z") == 35
        assert aic._base36_decode("10") == 36
        assert aic._base36_decode("1k9") == 2025  # lowercase allowed
        assert aic._base36_decode(" 1 k 9 ") == 2025  # spaces tolerated
        # generic value check: ABC -> 10*36^2 + 11*36 + 12
        assert aic._base36_decode("abc") == 10 * 36 * 36 + 11 * 36 + 12

    def test_base36_decode_invalid_chars(self):
        for s in ["*", "%", "@", "1-2", "G_1"]:
            with pytest.raises(ValueError):
                aic._base36_decode(s)


@pytest.mark.unit
class TestYearEncoding:
    def test_encode_year_b36_known_values(self):
        assert aic._encode_year_b36(2025) == "1K9"
        assert aic._encode_year_b36(0) == "000"
        assert aic._encode_year_b36(35) == "00Z"
        assert aic._encode_year_b36(36) == "010"


@pytest.mark.unit
class TestMsOfYear:
    def test_ms_of_year_at_year_start(self, monkeypatch):
        fixed = datetime(2025, 1, 1, 0, 0, 0, 0, tzinfo=BEIJING_TIMEZONE)
        monkeypatch.setattr(aic, "get_beijing_time", lambda: fixed)
        assert aic._get_ms_of_year() == 0

    def test_ms_of_year_first_seconds(self, monkeypatch):
        fixed = datetime(2025, 1, 1, 0, 0, 1, 234567, tzinfo=BEIJING_TIMEZONE)
        monkeypatch.setattr(aic, "get_beijing_time", lambda: fixed)
        # int(total_seconds()*1000) -> microseconds truncated
        assert aic._get_ms_of_year() == 1234

    def test_ms_of_year_end_of_year(self, monkeypatch):
        fixed = datetime(2024, 12, 31, 23, 59, 59, 999000, tzinfo=BEIJING_TIMEZONE)
        monkeypatch.setattr(aic, "get_beijing_time", lambda: fixed)
        # Compute expected similarly
        year_start = fixed.replace(
            month=1, day=1, hour=0, minute=0, second=0, microsecond=0
        )
        expected = int((fixed - year_start).total_seconds() * 1000)
        assert aic._get_ms_of_year() == expected


@pytest.mark.unit
class TestSerialFromMsWithSalt:
    def test_reproducible_and_kind_differs(self):
        ms = 1500
        salt = b"\x00\x00\x00\x00\x00\x00\x00\x00"
        s_obj = aic._serial_from_ms_with_salt(ms, salt, b"OBJ", 9)
        s_ins = aic._serial_from_ms_with_salt(ms, salt, b"INS", 8)
        assert isinstance(s_obj, str) and isinstance(s_ins, str)
        assert len(s_obj) == 9 and len(s_ins) == 8
        # Different kinds should yield different sequences
        assert s_obj != s_ins
        # Deterministic for same inputs
        assert aic._serial_from_ms_with_salt(ms, salt, b"OBJ", 9) == s_obj
        assert aic._serial_from_ms_with_salt(ms, salt, b"INS", 8) == s_ins

    def test_changes_with_salt_or_ms(self):
        ms = 1500
        salt1 = b"\x00\x00\x00\x00\x00\x00\x00\x00"
        salt2 = b"\x01\x00\x00\x00\x00\x00\x00\x00"
        s1 = aic._serial_from_ms_with_salt(ms, salt1, b"OBJ", 9)
        s2 = aic._serial_from_ms_with_salt(ms, salt2, b"OBJ", 9)
        assert s1 != s2
        s3 = aic._serial_from_ms_with_salt(ms + 1, salt1, b"OBJ", 9)
        assert s1 != s3

    def test_invalid_length_raises(self):
        with pytest.raises(ValueError):
            aic._serial_from_ms_with_salt(0, b"12345678", b"OBJ", 0)


@pytest.mark.unit
class TestCheckDigitsAndValidation:
    def _build_fixed_context(self, monkeypatch):
        # Fixed datetime for deterministic year and ms (2025-01-01 00:00:01.500)
        fixed = datetime(2025, 1, 1, 0, 0, 1, 500000, tzinfo=BEIJING_TIMEZONE)
        monkeypatch.setattr(aic, "get_beijing_time", lambda: fixed)
        # Fixed salt for secrets.token_bytes
        monkeypatch.setattr(aic.secrets, "token_bytes", lambda n: b"ABCDEFGH")
        # Precompute fields
        year_b36 = aic._encode_year_b36(2025)
        ms = aic._get_ms_of_year()
        obj = aic._serial_from_ms_with_salt(ms, b"ABCDEFGH", b"OBJ", 9)
        ins = aic._serial_from_ms_with_salt(ms, b"ABCDEFGH", b"INS", 8)
        body = f"1{'0001'}{'00001'}{year_b36}{obj}{ins}"
        chk = aic.calculate_check_digits(body)
        return body, chk

    def test_calculate_check_digits_happy(self, monkeypatch):
        body, chk = self._build_fixed_context(monkeypatch)
        # Should be 2 digits and satisfy GSMA-97 property
        n = aic._base36_decode(body)
        assert ((n * 100) + int(chk)) % 97 == 1
        assert len(chk) == 2 and chk.isdigit()

    def test_calculate_check_digits_invalid_length(self):
        with pytest.raises(ValueError):
            aic.calculate_check_digits("A" * 29)
        with pytest.raises(ValueError):
            aic.calculate_check_digits("A" * 31)

    def test_calculate_check_digits_edge_cases(self):
        # Test with all zeros
        body_zeros = "0" * 30
        chk_zeros = aic.calculate_check_digits(body_zeros)
        assert len(chk_zeros) == 2 and chk_zeros.isdigit()
        assert ((0 * 100) + int(chk_zeros)) % 97 == 1

        # Test with maximum base36 value
        body_max = "Z" * 30
        chk_max = aic.calculate_check_digits(body_max)
        assert len(chk_max) == 2 and chk_max.isdigit()
        n_max = aic._base36_decode(body_max)
        assert ((n_max * 100) + int(chk_max)) % 97 == 1

    def test_generate_aic_deterministic_with_patches(self, monkeypatch):
        body, chk = self._build_fixed_context(monkeypatch)
        generated = aic.generate_aic()
        assert len(generated) == 32
        assert generated[:30] == body
        assert generated[-2:] == chk
        assert aic.validate_aic(generated) is True

    def test_generate_aic_custom_codes_and_validation(self, monkeypatch):
        # Different but valid Base36 codes
        fixed = datetime(2025, 6, 2, 12, 0, 0, 0, tzinfo=BEIJING_TIMEZONE)
        monkeypatch.setattr(aic, "get_beijing_time", lambda: fixed)
        monkeypatch.setattr(aic.secrets, "token_bytes", lambda n: b"IJKL1234")
        custom = aic.generate_aic(
            protocol_version="2", manager_code="ABCD", provider_code="ZZZZZ"
        )
        assert len(custom) == 32
        assert custom[0] == "2"
        assert custom[1:5] == "ABCD"
        assert custom[5:10] == "ZZZZZ"
        assert aic.validate_aic(custom) is True

    def test_generate_aic_invalid_codes_raise(self, monkeypatch):
        # Wrong lengths cause check-digit computation to fail (body != 30 chars)
        fixed = datetime(2025, 1, 1, 0, 0, 0, 0, tzinfo=BEIJING_TIMEZONE)
        monkeypatch.setattr(aic, "get_beijing_time", lambda: fixed)
        monkeypatch.setattr(aic.secrets, "token_bytes", lambda n: b"ABCDEFGH")
        with pytest.raises(ValueError):
            aic.generate_aic(
                manager_code="001", provider_code="001"
            )  # lengths 3 and 3 -> body too short
        # Non-base36 characters lead to decode error during check digit computation
        with pytest.raises(ValueError):
            aic.generate_aic(manager_code="00*1", provider_code="00001")

    def test_validate_aic_various_failures(self, monkeypatch):
        # Build a valid base first
        body, chk = self._build_fixed_context(monkeypatch)
        valid = body + chk
        # Happy path is valid
        assert aic.validate_aic(valid) is True
        # Lowercase and spaces should also validate
        spaced = " ".join(list(valid.lower()))
        assert aic.validate_aic(spaced) is True
        # Wrong length
        assert aic.validate_aic(valid[:-1]) is False
        assert aic.validate_aic(valid + "0") is False
        # Non-digit check digits
        assert aic.validate_aic(valid[:30] + "AA") is False
        # Invalid Base36 char in body
        bad_body = list(valid)
        bad_body[5] = "-"  # break provider code char
        assert aic.validate_aic("".join(bad_body)) is False
        # Wrong checksum (modify last digit)
        wrong = valid[:-1] + ("0" if valid[-1] != "0" else "1")
        assert aic.validate_aic(wrong) is False
        # Empty input
        assert aic.validate_aic("") is False


@pytest.mark.unit
class TestGenerateAICComprehensive:
    """Comprehensive tests for generate_aic function focusing on edge cases and robustness."""

    def test_generate_aic_default_parameters(self):
        """Test generate_aic with default parameters produces valid AIC."""
        aic_code = aic.generate_aic()
        assert len(aic_code) == 32
        assert aic.validate_aic(aic_code) is True
        # Check default codes are used
        assert aic_code[0] == "1"  # protocol version
        assert aic_code[1:5] == "0001"  # manager code
        assert aic_code[5:10] == "00001"  # provider code

    def test_generate_aic_different_years(self, monkeypatch):
        """Test AIC generation across different years."""
        test_years = [2020, 2025, 2030, 2050, 2100]
        for year in test_years:
            fixed = datetime(year, 6, 15, 12, 30, 45, tzinfo=BEIJING_TIMEZONE)
            monkeypatch.setattr(aic, "get_beijing_time", lambda: fixed)
            aic_code = aic.generate_aic()
            assert len(aic_code) == 32
            assert aic.validate_aic(aic_code) is True
            # Verify year encoding
            year_b36 = aic._encode_year_b36(year)
            assert aic_code[10:13] == year_b36

    def test_generate_aic_boundary_times(self, monkeypatch):
        """Test AIC generation at boundary times (start/end of year)."""
        # Start of year
        start_of_year = datetime(2025, 1, 1, 0, 0, 0, 0, tzinfo=BEIJING_TIMEZONE)
        monkeypatch.setattr(aic, "get_beijing_time", lambda: start_of_year)
        aic_start = aic.generate_aic()
        assert len(aic_start) == 32
        assert aic.validate_aic(aic_start) is True

        # End of year
        end_of_year = datetime(
            2025, 12, 31, 23, 59, 59, 999000, tzinfo=BEIJING_TIMEZONE
        )
        monkeypatch.setattr(aic, "get_beijing_time", lambda: end_of_year)
        aic_end = aic.generate_aic()
        assert len(aic_end) == 32
        assert aic.validate_aic(aic_end) is True

        # They should be different due to different ms_in_year
        assert aic_start != aic_end

    def test_generate_aic_uniqueness_across_calls(self):
        """Test that multiple calls to generate_aic produce unique results."""
        aics = set()
        for _ in range(100):
            new_aic = aic.generate_aic()
            assert new_aic not in aics, f"Duplicate AIC generated: {new_aic}"
            aics.add(new_aic)
            assert aic.validate_aic(new_aic) is True

    def test_generate_aic_extreme_custom_codes(self, monkeypatch):
        """Test generate_aic with extreme but valid custom codes."""
        fixed = datetime(2025, 1, 1, 0, 0, 0, 0, tzinfo=BEIJING_TIMEZONE)
        monkeypatch.setattr(aic, "get_beijing_time", lambda: fixed)

        # Test with all zeros
        aic_zeros = aic.generate_aic(
            protocol_version="0", manager_code="0000", provider_code="00000"
        )
        assert len(aic_zeros) == 32
        assert aic.validate_aic(aic_zeros) is True
        assert aic_zeros[0] == "0"
        assert aic_zeros[1:5] == "0000"
        assert aic_zeros[5:10] == "00000"

        # Test with maximum base36 values
        aic_max = aic.generate_aic(
            protocol_version="Z", manager_code="ZZZZ", provider_code="ZZZZZ"
        )
        assert len(aic_max) == 32
        assert aic.validate_aic(aic_max) is True
        assert aic_max[0] == "Z"
        assert aic_max[1:5] == "ZZZZ"
        assert aic_max[5:10] == "ZZZZZ"

    def test_generate_aic_invalid_parameter_lengths(self):
        """Test generate_aic with invalid parameter lengths."""
        # Protocol version must be 1 character
        with pytest.raises(ValueError):
            aic.generate_aic(protocol_version="")
        with pytest.raises(ValueError):
            aic.generate_aic(protocol_version="12")

        # Manager code must be 4 characters
        with pytest.raises(ValueError):
            aic.generate_aic(manager_code="123")
        with pytest.raises(ValueError):
            aic.generate_aic(manager_code="12345")

        # Provider code must be 5 characters
        with pytest.raises(ValueError):
            aic.generate_aic(provider_code="1234")
        with pytest.raises(ValueError):
            aic.generate_aic(provider_code="123456")

    def test_generate_aic_invalid_base36_characters(self):
        """Test generate_aic with invalid Base36 characters."""
        invalid_chars = [
            "!",
            "@",
            "#",
            "$",
            "%",
            "^",
            "&",
            "*",
            "(",
            ")",
            "-",
            "=",
            "+",
        ]
        for char in invalid_chars:
            with pytest.raises(ValueError):
                aic.generate_aic(protocol_version=char)
            with pytest.raises(ValueError):
                aic.generate_aic(manager_code=f"000{char}")
            with pytest.raises(ValueError):
                aic.generate_aic(provider_code=f"0000{char}")


@pytest.mark.unit
class TestValidateAICComprehensive:
    """Comprehensive tests for validate_aic function focusing on all possible failure modes."""

    def test_validate_aic_none_and_empty_inputs(self):
        """Test validate_aic with None and empty inputs."""
        assert aic.validate_aic(None) is False
        assert aic.validate_aic("") is False
        assert aic.validate_aic(" ") is False
        assert aic.validate_aic("\t") is False
        assert aic.validate_aic("\n") is False

    def test_validate_aic_length_variations(self, monkeypatch):
        """Test validate_aic with various incorrect lengths."""
        # Generate a valid AIC first
        fixed = datetime(2025, 1, 1, 0, 0, 0, 0, tzinfo=BEIJING_TIMEZONE)
        monkeypatch.setattr(aic, "get_beijing_time", lambda: fixed)
        monkeypatch.setattr(aic.secrets, "token_bytes", lambda n: b"TESTTEST")
        valid_aic = aic.generate_aic()

        # Test various wrong lengths
        for length in [1, 10, 20, 30, 31, 33, 40, 50]:
            if length < 32:
                truncated = valid_aic[:length]
                assert aic.validate_aic(truncated) is False
            else:
                extended = valid_aic + "0" * (length - 32)
                assert aic.validate_aic(extended) is False

    def test_validate_aic_checksum_digit_variations(self, monkeypatch):
        """Test validate_aic with all possible checksum digit variations."""
        # Generate a valid AIC first
        fixed = datetime(2025, 1, 1, 0, 0, 0, 0, tzinfo=BEIJING_TIMEZONE)
        monkeypatch.setattr(aic, "get_beijing_time", lambda: fixed)
        monkeypatch.setattr(aic.secrets, "token_bytes", lambda n: b"TESTTEST")
        valid_aic = aic.generate_aic()
        body = valid_aic[:30]
        correct_checksum = valid_aic[30:]

        # Test all possible 2-digit combinations except the correct one
        for i in range(100):
            test_checksum = f"{i:02d}"
            if test_checksum != correct_checksum:
                test_aic = body + test_checksum
                assert (
                    aic.validate_aic(test_aic) is False
                ), f"False positive for checksum {test_checksum}"

    def test_validate_aic_non_digit_checksums(self, monkeypatch):
        """Test validate_aic with non-digit characters in checksum positions."""
        # Generate a valid AIC body
        fixed = datetime(2025, 1, 1, 0, 0, 0, 0, tzinfo=BEIJING_TIMEZONE)
        monkeypatch.setattr(aic, "get_beijing_time", lambda: fixed)
        monkeypatch.setattr(aic.secrets, "token_bytes", lambda n: b"TESTTEST")
        valid_aic = aic.generate_aic()
        body = valid_aic[:30]

        # Test with letters and symbols in checksum
        invalid_checksums = ["AA", "AB", "0A", "A0", "!@", "**", "  ", "1!", "!1"]
        for invalid_checksum in invalid_checksums:
            test_aic = body + invalid_checksum
            assert aic.validate_aic(test_aic) is False

    def test_validate_aic_invalid_base36_in_body(self, monkeypatch):
        """Test validate_aic with invalid Base36 characters in body."""
        # Generate a valid AIC first
        fixed = datetime(2025, 1, 1, 0, 0, 0, 0, tzinfo=BEIJING_TIMEZONE)
        monkeypatch.setattr(aic, "get_beijing_time", lambda: fixed)
        monkeypatch.setattr(aic.secrets, "token_bytes", lambda n: b"TESTTEST")
        valid_aic = aic.generate_aic()

        # Test invalid characters at different positions in body
        invalid_chars = [
            "!",
            "@",
            "#",
            "$",
            "%",
            "^",
            "&",
            "*",
            "(",
            ")",
            "-",
            "=",
            "+",
            "?",
            "/",
            "\\",
            "|",
        ]
        for pos in [0, 5, 10, 15, 20, 25, 29]:  # Test at various positions
            for char in invalid_chars:
                test_aic = list(valid_aic)
                test_aic[pos] = char
                assert aic.validate_aic("".join(test_aic)) is False

    def test_validate_aic_whitespace_handling(self, monkeypatch):
        """Test validate_aic properly handles whitespace."""
        # Generate a valid AIC
        fixed = datetime(2025, 1, 1, 0, 0, 0, 0, tzinfo=BEIJING_TIMEZONE)
        monkeypatch.setattr(aic, "get_beijing_time", lambda: fixed)
        monkeypatch.setattr(aic.secrets, "token_bytes", lambda n: b"TESTTEST")
        valid_aic = aic.generate_aic()

        # Test with various whitespace patterns
        whitespace_variations = [
            f" {valid_aic} ",
            f"  {valid_aic}  ",
            f"\t{valid_aic}\t",
            f"\n{valid_aic}\n",
            " ".join(valid_aic),  # Space between every character
            f"{valid_aic[:16]} {valid_aic[16:]}",  # Space in middle
        ]

        for variation in whitespace_variations:
            assert (
                aic.validate_aic(variation) is True
            ), f"Failed for variation: {repr(variation)}"

    def test_validate_aic_case_insensitive(self, monkeypatch):
        """Test validate_aic is case insensitive."""
        # Generate a valid AIC
        fixed = datetime(2025, 1, 1, 0, 0, 0, 0, tzinfo=BEIJING_TIMEZONE)
        monkeypatch.setattr(aic, "get_beijing_time", lambda: fixed)
        monkeypatch.setattr(aic.secrets, "token_bytes", lambda n: b"TESTTEST")
        valid_aic = aic.generate_aic()

        # Test various case combinations
        case_variations = [
            valid_aic.lower(),
            valid_aic.upper(),
            "".join(
                [
                    c.lower() if i % 2 == 0 else c.upper()
                    for i, c in enumerate(valid_aic)
                ]
            ),
            "".join(
                [
                    c.upper() if i % 2 == 0 else c.lower()
                    for i, c in enumerate(valid_aic)
                ]
            ),
        ]

        for variation in case_variations:
            assert (
                aic.validate_aic(variation) is True
            ), f"Failed for case variation: {variation}"

    def test_validate_aic_mathematical_properties(self, monkeypatch):
        """Test that validate_aic correctly implements GSMA-97 mathematical properties."""
        # Generate multiple valid AICs and verify the mathematical property
        fixed = datetime(2025, 1, 1, 0, 0, 0, 0, tzinfo=BEIJING_TIMEZONE)
        monkeypatch.setattr(aic, "get_beijing_time", lambda: fixed)

        for i in range(10):
            monkeypatch.setattr(aic.secrets, "token_bytes", lambda n: bytes([i] * 8))
            valid_aic = aic.generate_aic()

            # Manually verify the mathematical property
            body = valid_aic[:30].upper().replace(" ", "")
            checksum = valid_aic[30:]

            n = aic._base36_decode(body)
            checksum_val = int(checksum)

            # The GSMA property: (N * 100 + checksum) % 97 == 1
            assert ((n * 100) + checksum_val) % 97 == 1
            assert aic.validate_aic(valid_aic) is True

    def test_validate_aic_edge_case_bodies(self):
        """Test validate_aic with edge case body values."""
        # Test with all zeros body
        zeros_body = "0" * 30
        zeros_checksum = aic.calculate_check_digits(zeros_body)
        zeros_aic = zeros_body + zeros_checksum
        assert aic.validate_aic(zeros_aic) is True

        # Test with maximum base36 body
        max_body = "Z" * 30
        max_checksum = aic.calculate_check_digits(max_body)
        max_aic = max_body + max_checksum
        assert aic.validate_aic(max_aic) is True

        # Test with mixed case edge values
        mixed_body = "0" * 15 + "Z" * 15
        mixed_checksum = aic.calculate_check_digits(mixed_body)
        mixed_aic = mixed_body + mixed_checksum
        assert aic.validate_aic(mixed_aic) is True
