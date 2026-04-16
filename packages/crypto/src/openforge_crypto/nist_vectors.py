"""NIST CAVP test vector loader for post-quantum cryptographic algorithms.

Supports loading and parsing Known Answer Test (KAT) files for:
  - ML-KEM (FIPS 203) -- Module Lattice Key Encapsulation
  - ML-DSA (FIPS 204) -- Module Lattice Digital Signature Algorithm
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


class Algorithm(Enum):
    """Supported NIST post-quantum algorithms."""

    ML_KEM_512 = auto()
    ML_KEM_768 = auto()
    ML_KEM_1024 = auto()
    ML_DSA_44 = auto()
    ML_DSA_65 = auto()
    ML_DSA_87 = auto()


@dataclass(frozen=True, slots=True)
class TestVector:
    """A single NIST CAVP test vector."""

    algorithm: Algorithm
    count: int
    fields: dict[str, bytes]
    metadata: dict[str, str] = field(default_factory=dict)

    def get_hex(self, field_name: str) -> str:
        """Return a field value as a hex string."""
        return self.fields[field_name].hex()

    def get_int(self, field_name: str) -> int:
        """Return a field value as an integer."""
        return int.from_bytes(self.fields[field_name], byteorder="big")

    def __repr__(self) -> str:
        field_names = ", ".join(self.fields.keys())
        return (
            f"TestVector(algorithm={self.algorithm.name}, "
            f"count={self.count}, fields=[{field_names}])"
        )


# Mapping from algorithm name strings (as found in NIST files) to enum.
_ALGO_NAME_MAP: dict[str, Algorithm] = {
    "ML-KEM-512": Algorithm.ML_KEM_512,
    "ML-KEM-768": Algorithm.ML_KEM_768,
    "ML-KEM-1024": Algorithm.ML_KEM_1024,
    "ML-DSA-44": Algorithm.ML_DSA_44,
    "ML-DSA-65": Algorithm.ML_DSA_65,
    "ML-DSA-87": Algorithm.ML_DSA_87,
    # Legacy names
    "KYBER512": Algorithm.ML_KEM_512,
    "KYBER768": Algorithm.ML_KEM_768,
    "KYBER1024": Algorithm.ML_KEM_1024,
    "DILITHIUM2": Algorithm.ML_DSA_44,
    "DILITHIUM3": Algorithm.ML_DSA_65,
    "DILITHIUM5": Algorithm.ML_DSA_87,
}

# Expected field names per algorithm family
ML_KEM_KEYGEN_FIELDS: frozenset[str] = frozenset(
    {
        "z",
        "d",
        "ek",
        "dk",
    }
)

ML_KEM_ENCAPS_FIELDS: frozenset[str] = frozenset(
    {
        "ek",
        "m",
        "K",
        "c",
    }
)

ML_KEM_DECAPS_FIELDS: frozenset[str] = frozenset(
    {
        "dk",
        "c",
        "K",
    }
)

ML_DSA_KEYGEN_FIELDS: frozenset[str] = frozenset(
    {
        "xi",
        "pk",
        "sk",
    }
)

ML_DSA_SIGN_FIELDS: frozenset[str] = frozenset(
    {
        "sk",
        "message",
        "rnd",
        "signature",
    }
)

ML_DSA_VERIFY_FIELDS: frozenset[str] = frozenset(
    {
        "pk",
        "message",
        "signature",
    }
)


class NISTVectorLoader:
    """Load and parse NIST CAVP test vector files.

    Handles the standard NIST response file format with ``count``,
    hex-encoded field values, and header comments.

    Usage::

        loader = NISTVectorLoader()
        vectors = loader.load(Path("ML-KEM-512-KeyGen.rsp"), Algorithm.ML_KEM_512)
        for vec in vectors:
            print(vec.count, vec.get_hex("ek")[:32], "...")
    """

    # Regex for key = value lines (value is hex string or integer)
    _KV_PATTERN: re.Pattern[str] = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$")

    def load(
        self,
        path: Path,
        algorithm: Algorithm,
        *,
        max_vectors: int | None = None,
    ) -> list[TestVector]:
        """Load test vectors from a NIST CAVP response (.rsp) file.

        Parameters
        ----------
        path:
            Path to the .rsp or .txt file.
        algorithm:
            The algorithm these vectors target.
        max_vectors:
            Optional limit on the number of vectors to load.

        Returns
        -------
        list[TestVector]
            Parsed test vectors.
        """
        text = path.read_text(encoding="utf-8", errors="replace")
        return list(self._parse(text, algorithm, max_vectors))

    def load_from_string(
        self,
        content: str,
        algorithm: Algorithm,
        *,
        max_vectors: int | None = None,
    ) -> list[TestVector]:
        """Parse test vectors from an in-memory string."""
        return list(self._parse(content, algorithm, max_vectors))

    def load_directory(
        self,
        directory: Path,
        *,
        max_vectors_per_file: int | None = None,
    ) -> dict[Algorithm, list[TestVector]]:
        """Load all .rsp files in a directory, auto-detecting algorithm names.

        Parameters
        ----------
        directory:
            Directory containing .rsp files.
        max_vectors_per_file:
            Optional per-file vector limit.

        Returns
        -------
        dict[Algorithm, list[TestVector]]
            Mapping from detected algorithm to its test vectors.
        """
        results: dict[Algorithm, list[TestVector]] = {}

        for rsp_file in sorted(directory.glob("*.rsp")):
            algo = self._detect_algorithm(rsp_file)
            if algo is None:
                continue
            vectors = self.load(rsp_file, algo, max_vectors=max_vectors_per_file)
            results.setdefault(algo, []).extend(vectors)

        return results

    def validate(
        self,
        vectors: list[TestVector],
        required_fields: frozenset[str],
    ) -> list[str]:
        """Validate that every vector contains the required fields.

        Returns a list of error messages (empty if all valid).
        """
        errors: list[str] = []
        for vec in vectors:
            missing = required_fields - vec.fields.keys()
            if missing:
                errors.append(f"Vector count={vec.count}: missing fields {sorted(missing)}")
        return errors

    # ── Internal parsing ───────────────────────────────────────────

    def _parse(
        self,
        text: str,
        algorithm: Algorithm,
        max_vectors: int | None,
    ) -> Iterator[TestVector]:
        """Yield parsed TestVector objects from raw file text."""
        metadata: dict[str, str] = {}
        current_fields: dict[str, bytes] = {}
        current_count: int = -1
        yielded: int = 0

        for line in text.splitlines():
            line = line.strip()

            # Skip blank lines and comments
            if not line:
                # A blank line signals end of current vector block
                if current_count >= 0 and current_fields:
                    yield TestVector(
                        algorithm=algorithm,
                        count=current_count,
                        fields=dict(current_fields),
                        metadata=dict(metadata),
                    )
                    yielded += 1
                    if max_vectors is not None and yielded >= max_vectors:
                        return
                    current_fields = {}
                    current_count = -1
                continue

            if line.startswith("#"):
                # Header comment -- extract metadata
                comment = line.lstrip("#").strip()
                if "=" in comment:
                    key, _, val = comment.partition("=")
                    metadata[key.strip()] = val.strip()
                continue

            if line.startswith("[") and line.endswith("]"):
                # Section header (e.g., [ML-KEM-512])
                section = line[1:-1].strip()
                if section in _ALGO_NAME_MAP:
                    # Override algorithm if file contains section markers
                    pass
                continue

            match = self._KV_PATTERN.match(line)
            if match is None:
                continue

            key = match.group(1)
            value = match.group(2).strip()

            if key.lower() == "count":
                current_count = int(value)
            else:
                # Try to decode as hex, fall back to storing as UTF-8 bytes
                current_fields[key] = self._decode_value(value)

        # Flush last vector if file does not end with blank line
        if current_count >= 0 and current_fields:
            yield TestVector(
                algorithm=algorithm,
                count=current_count,
                fields=dict(current_fields),
                metadata=dict(metadata),
            )

    @staticmethod
    def _decode_value(value: str) -> bytes:
        """Decode a value string as hex bytes, or fall back to UTF-8."""
        # NIST files use uppercase hex without prefix
        cleaned = value.replace(" ", "")
        try:
            return bytes.fromhex(cleaned)
        except ValueError:
            return value.encode("utf-8")

    @staticmethod
    def _detect_algorithm(path: Path) -> Algorithm | None:
        """Attempt to detect the algorithm from the file name."""
        stem = path.stem.upper().replace("_", "-")
        for name, algo in _ALGO_NAME_MAP.items():
            if name.upper().replace("_", "-") in stem:
                return algo
        return None
