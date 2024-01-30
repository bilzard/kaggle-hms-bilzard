from pathlib import Path

import numpy as np
import polars as pl
from tqdm import tqdm


def train_valid_split(metadata: pl.DataFrame, fold_split_df: pl.DataFrame, fold: int):
    eeg_ids_train = (
        fold_split_df.filter(pl.col("fold").eq(fold).not_())
        .select("eeg_id")
        .to_numpy()
        .flatten()
    )
    eeg_ids_valid = (
        fold_split_df.filter(pl.col("fold").eq(fold))
        .select("eeg_id")
        .to_numpy()
        .flatten()
    )
    train_df = metadata.filter(pl.col("eeg_id").is_in(eeg_ids_train))
    valid_df = metadata.filter(pl.col("eeg_id").is_in(eeg_ids_valid))
    return train_df, valid_df


def preload_eegs(
    eeg_ids: list[int],
    preprocess_dir: Path,
):
    id2eeg = dict()
    for eeg_id in tqdm(eeg_ids):
        eeg = np.load(preprocess_dir / str(eeg_id) / "eeg.npy")
        id2eeg[eeg_id] = eeg

    return id2eeg


def preload_cqf(
    eeg_ids: list[int],
    preprocess_dir: Path,
):
    id2cqf = dict()
    for eeg_id in tqdm(eeg_ids):
        cqf = np.load(preprocess_dir / str(eeg_id) / "cqf.npy")
        id2cqf[eeg_id] = cqf

    return id2cqf


def preload_mask(
    eeg_ids: list[int],
    preprocess_dir: Path,
):
    id2mask = dict()
    for eeg_id in tqdm(eeg_ids):
        mask = np.load(preprocess_dir / str(eeg_id) / "mask.npy")
        id2mask[eeg_id] = mask

    return id2mask