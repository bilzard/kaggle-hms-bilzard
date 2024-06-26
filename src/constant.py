LABELS = ["seizure", "lpd", "gpd", "lrda", "grda", "other"]
PROBE2IDX = {
    "Fp1": 0,
    "F3": 1,
    "C3": 2,
    "P3": 3,
    "F7": 4,
    "T3": 5,
    "T5": 6,
    "O1": 7,
    "Fz": 8,
    "Cz": 9,
    "Pz": 10,
    "Fp2": 11,
    "F4": 12,
    "C4": 13,
    "P4": 14,
    "F8": 15,
    "T4": 16,
    "T6": 17,
    "O2": 18,
    "EKG": 19,
}
PROBE_GROUPS = dict(
    LL=["Fp1", "F7", "T3", "T5", "O1"],
    LP=["Fp1", "F3", "C3", "P3", "O1"],
    Z=["Fz", "Cz", "Pz"],
    RP=["Fp2", "F4", "C4", "P4", "O2"],
    RL=["Fp2", "F8", "T4", "T6", "O2"],
)
BG_PROBE_GROUPS = ["LL" "LP" "RL" "RP"]
IDX2PROBE = {v: k for k, v in PROBE2IDX.items()}
PROBES = list(PROBE2IDX.keys())
EEG_PROBES = PROBES[:-1]
KEG_PROBE = PROBES[-1]
