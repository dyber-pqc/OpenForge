"""OpenForge EDA cryptographic verification and side-channel analysis."""

__version__ = "0.1.0"

# Constant-time verification
from openforge_crypto.constant_time import (
    ConstantTimeVerifier,
    CTReport,
    TaintLevel,
    Violation,
    ViolationKind,
)

# Entropy flow analysis
from openforge_crypto.entropy import (
    ConditioningType,
    EntropyConditioner,
    EntropyFlowAnalyzer,
    EntropyFlowReport,
    EntropyIssue,
    EntropySink,
    EntropySinkPurpose,
    EntropySource,
    EntropySourceType,
    HealthTestType,
    IssueSeverity,
)

# Fault injection simulation
from openforge_crypto.fault_injection import (
    DFAResult,
    FaultClassification,
    FaultConfig,
    FaultInjectionSimulator,
    FaultModel,
    FaultResilienceReport,
    FaultResult,
)

# FIPS 140-3 compliance
from openforge_crypto.fips import (
    CheckResult as FIPSCheckResult,
)
from openforge_crypto.fips import (
    CheckStatus,
    FIPSComplianceChecker,
    FIPSLevel,
    FIPSReport,
)

# NIST test vector loading
from openforge_crypto.nist_vectors import (
    Algorithm,
    NISTVectorLoader,
    TestVector,
)

# NTT / polynomial validation
from openforge_crypto.ntt import (
    DILITHIUM_Q,
    DILITHIUM_ZETAS,
    KYBER_Q,
    KYBER_ZETAS,
    NTTResult,
    NTTStandard,
    NTTValidator,
    TwiddleResult,
)

# Side-channel simulation
from openforge_crypto.side_channel import (
    CPAResult,
    PowerTrace,
    SideChannelSimulator,
    TVLAResult,
)

__all__ = [
    # constant_time
    "ConstantTimeVerifier",
    "CTReport",
    "TaintLevel",
    "Violation",
    "ViolationKind",
    # side_channel
    "CPAResult",
    "PowerTrace",
    "SideChannelSimulator",
    "TVLAResult",
    # nist_vectors
    "Algorithm",
    "NISTVectorLoader",
    "TestVector",
    # fips
    "CheckStatus",
    "FIPSCheckResult",
    "FIPSComplianceChecker",
    "FIPSLevel",
    "FIPSReport",
    # entropy
    "ConditioningType",
    "EntropyConditioner",
    "EntropyFlowAnalyzer",
    "EntropyFlowReport",
    "EntropyIssue",
    "EntropySink",
    "EntropySinkPurpose",
    "EntropySource",
    "EntropySourceType",
    "HealthTestType",
    "IssueSeverity",
    # fault_injection
    "DFAResult",
    "FaultClassification",
    "FaultConfig",
    "FaultInjectionSimulator",
    "FaultModel",
    "FaultResilienceReport",
    "FaultResult",
    # ntt
    "DILITHIUM_Q",
    "DILITHIUM_ZETAS",
    "KYBER_Q",
    "KYBER_ZETAS",
    "NTTResult",
    "NTTStandard",
    "NTTValidator",
    "TwiddleResult",
]
