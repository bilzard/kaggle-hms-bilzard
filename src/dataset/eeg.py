import numpy as np
import polars as pl
import torch
from torch.utils.data import DataLoader, Dataset

from src.array_util import pad_multiple_of
from src.constant import LABELS
from src.transform import BaseTransform


def row_to_dict(row: dict, exclude_keys: list[str]):
    return {key: value for key, value in row.items() if key not in exclude_keys}


def pad_eeg(
    eeg: np.ndarray, cqf: np.ndarray, duration: int, padding_type: str
) -> tuple[np.ndarray, np.ndarray]:
    eeg = pad_multiple_of(
        eeg,
        duration,
        0,
        padding_type=padding_type,
        mode="reflect",
    )
    cqf = pad_multiple_of(
        cqf,
        duration,
        0,
        padding_type=padding_type,
        mode="constant",
        constant_values=0,
    )
    return eeg, cqf


def sample_eeg(
    eeg: np.ndarray,
    mask: np.ndarray,
    duration: int,
    padding_type: str,
    num_samples: int,
    generator: torch.Generator | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """
    eeg: (num_frames, num_channels)
    mask: (num_frames, num_channels)

    return
    ------
    eeg: (num_samples, duration, num_channels)
    mask: (num_samples, duration, num_channels)
    """
    eeg_org, mask_org = eeg, mask
    num_frames = eeg.shape[0]

    eegs = []
    cqfs = []
    for _ in range(num_samples):
        if num_frames < duration:
            eeg, cqf = pad_eeg(eeg_org, mask_org, duration, padding_type)
        else:
            start_frame = torch.randint(
                num_frames - duration + 1, (1,), generator=generator
            ).item()
            eeg = eeg_org[start_frame : start_frame + duration]
            cqf = mask_org[start_frame : start_frame + duration]

        eegs.append(eeg.copy())
        cqfs.append(cqf.copy())

    eeg = np.stack(eegs, axis=0)  # S, T, C
    mask = np.stack(cqfs, axis=0)  # S, T, C

    return eeg, mask


class HmsBaseDataset(Dataset):
    def __init__(
        self,
        metadata: pl.DataFrame,
        id2eeg: dict[int, np.ndarray],
        id2cqf: dict[int, np.ndarray],
        padding_type: str = "right",
        duration: int = 2048,
        weight_key: str = "weight_per_eeg",
        transform: BaseTransform | None = None,
        transform_enabled: bool = False,
        seed: int = 42,
        with_label: bool = True,
        **kwargs,
    ):
        self.metadata = metadata
        self.id2eeg = id2eeg
        self.id2cqf = id2cqf
        self.padding_type = padding_type
        self.duration = duration
        self.weight_key = weight_key
        self.seed = seed
        self.with_label = with_label

        self._transform_enabled = transform_enabled
        self._args = dict(
            padding_type=padding_type,
            duration=duration,
            weight_key=weight_key,
            transform_enabled=transform_enabled,
            seed=seed,
            transform=transform,
            with_label=with_label,
            **kwargs,
        )
        self._generator = torch.Generator()
        self.reset()
        self._transform = transform

    @property
    def transform_enabled(self):
        return self._transform_enabled

    @property
    def generator(self):
        return self._generator

    def enable_transform(self):
        self._transform_enabled = True

    def disable_transform(self):
        self._transform_enabled = False

    def __repr__(self):
        arg_str = ",\n    ".join([f"{k}={v}" for k, v in self._args.items()])
        return f"""{self.__class__.__name__}({arg_str})"""

    def reset(self):
        self._generator.manual_seed(self.seed)
        print(f"[INFO] {self.__class__.__name__}: seed is reset to {self.seed}")

    def apply_transform(self, eeg, cqf) -> tuple[np.ndarray, np.ndarray]:
        if self._transform_enabled and self._transform is not None:
            return self._transform(eeg, cqf)
        return eeg, cqf


class SlidingWindowPerEegDataset(HmsBaseDataset):
    def __init__(
        self,
        metadata: pl.DataFrame,
        id2eeg: dict[int, np.ndarray],
        id2cqf: dict[int, np.ndarray],
        padding_type: str = "right",
        duration: int = 2048,
        stride: int = 2048,
        weight_key: str = "weight_per_eeg",
        **kwdargs,
    ):
        metadata = metadata.group_by("eeg_id", maintain_order=True).agg(
            *[pl.col(f"{label}_vote_per_eeg").first() for label in LABELS],
            pl.col(weight_key).first(),
            *[pl.col(f"{label}_prob_per_eeg").first() for label in LABELS],
            pl.col("min_eeg_label_offset_sec").first(),
            pl.col("max_eeg_label_offset_sec").first(),
        )
        super().__init__(
            metadata, id2eeg, id2cqf, padding_type, duration, weight_key, stride=stride
        )
        self.stride = stride
        self.eeg_ids = sorted(self.metadata["eeg_id"].to_list())
        self.eeg_id2metadata = {
            row["eeg_id"]: row_to_dict(row, exclude_keys=["eeg_id"])
            for row in self.metadata.to_dicts()
        }

    def __len__(self):
        return len(self.eeg_ids)

    def __getitem__(self, idx):
        eeg_id = self.eeg_ids[idx]
        eegs, cqfs = [], []

        eeg_org = self.id2eeg[eeg_id].astype(np.float32)
        cqf_org = self.id2cqf[eeg_id].astype(np.float32)
        eeg_org, cqf_org = pad_eeg(eeg_org, cqf_org, self.duration, self.padding_type)

        num_frames = eeg_org.shape[0]
        row = self.eeg_id2metadata[eeg_id]
        for start_frame in range(0, num_frames - self.duration + 1, self.stride):
            end_frame = start_frame + self.duration
            eeg = eeg_org[start_frame:end_frame]
            cqf = cqf_org[start_frame:end_frame]
            eegs.append(eeg.copy())
            cqfs.append(cqf.copy())

        eeg = np.stack(eegs, axis=0)
        cqf = np.stack(cqfs, axis=0)

        label = np.array(
            [row[f"{label}_prob_per_eeg"] for label in LABELS], dtype=np.float32
        )
        weight = np.array([row[self.weight_key]], dtype=np.float32)
        data = dict(eeg_id=eeg_id, eeg=eeg, cqf=cqf, label=label, weight=weight)

        return data


class SlidingWindowEegDataset(HmsBaseDataset):
    def __init__(
        self,
        metadata: pl.DataFrame,
        id2eeg: dict[int, np.ndarray],
        id2cqf: dict[int, np.ndarray],
        padding_type: str = "right",
        duration: int = 2048,
        stride: int = 2048,
        weight_key: str = "weight_per_eeg",
        **kwdargs,
    ):
        metadata = metadata.group_by("eeg_id", maintain_order=True).agg(
            *[pl.col(f"{label}_vote_per_eeg").first() for label in LABELS],
            pl.col(weight_key).first(),
            *[pl.col(f"{label}_prob_per_eeg").first() for label in LABELS],
            pl.col("min_eeg_label_offset_sec").first(),
            pl.col("max_eeg_label_offset_sec").first(),
        )
        super().__init__(
            metadata, id2eeg, id2cqf, padding_type, duration, weight_key, stride=stride
        )
        self.stride = stride
        self.eeg_ids = sorted(self.metadata["eeg_id"].to_list())
        self.eeg_id2metadata = {
            row["eeg_id"]: row_to_dict(row, exclude_keys=["eeg_id"])
            for row in self.metadata.to_dicts()
        }
        self.chunks = self._generate_chunks()

    def _generate_chunks(self):
        chunks = []
        for eeg_id in self.eeg_ids:
            eeg = self.id2eeg[eeg_id]
            num_frames = eeg.shape[0]
            for start_frame in range(0, num_frames - self.duration + 1, self.stride):
                end_frame = start_frame + self.duration
                chunks.append((eeg_id, start_frame, end_frame))

        return chunks

    def __len__(self):
        return len(self.chunks)

    def __getitem__(self, idx):
        eeg_id, start_frame, end_frame = self.chunks[idx]
        row = self.eeg_id2metadata[eeg_id]

        eeg = self.id2eeg[eeg_id][start_frame:end_frame].astype(np.float32)
        cqf = self.id2cqf[eeg_id][start_frame:end_frame].astype(np.float32)

        eeg, cqf = pad_eeg(eeg, cqf, self.duration, self.padding_type)

        label = np.array(
            [row[f"{label}_prob_per_eeg"] for label in LABELS], dtype=np.float32
        )
        weight = np.array([row[self.weight_key]], dtype=np.float32)
        data = dict(eeg_id=eeg_id, eeg=eeg, cqf=cqf, label=label, weight=weight)

        return data


class UniformSamplingEegDataset(HmsBaseDataset):
    """
    EEGからdurationのchunkをランダムにサンプリングする。
    """

    def __init__(
        self,
        metadata: pl.DataFrame,
        id2eeg: dict[int, np.ndarray],
        id2cqf: dict[int, np.ndarray],
        padding_type: str = "right",
        duration: int = 2048,
        transform: BaseTransform | None = None,
        num_samples_per_eeg: int = 1,
        weight_key: str = "weight_per_eeg",
        seed: int = 42,
        transform_enabled: bool = False,
        **kwdargs,
    ):
        metadata = metadata.group_by("eeg_id", maintain_order=True).agg(
            *[pl.col(f"{label}_vote_per_eeg").first() for label in LABELS],
            pl.col(weight_key).first(),
            *[pl.col(f"{label}_prob_per_eeg").first() for label in LABELS],
            pl.col("min_eeg_label_offset_sec").first(),
            pl.col("max_eeg_label_offset_sec").first(),
            pl.col("loss").first(),
        )
        super().__init__(
            metadata,
            id2eeg,
            id2cqf,
            padding_type,
            duration,
            weight_key,
            num_samples_per_eeg=num_samples_per_eeg,
            seed=seed,
            transform_enabled=transform_enabled,
            transform=transform,
        )
        self.num_samples_per_eeg = num_samples_per_eeg
        self.eeg_ids = sorted(self.metadata["eeg_id"].to_list())
        self.eeg_id2metadata = {
            row["eeg_id"]: row_to_dict(row, exclude_keys=["eeg_id"])
            for row in self.metadata.to_dicts()
        }

    def __len__(self):
        return len(self.eeg_ids)

    def __getitem__(self, idx):
        eeg_id = self.eeg_ids[idx]
        row = self.eeg_id2metadata[eeg_id]

        eeg = self.id2eeg[eeg_id].astype(np.float32)
        cqf = self.id2cqf[eeg_id].astype(np.float32)

        eeg, cqf = sample_eeg(
            eeg,
            cqf,
            self.duration,
            self.padding_type,
            self.num_samples_per_eeg,
            self.generator,
        )

        label = np.array(
            [row[f"{label}_prob_per_eeg"] for label in LABELS], dtype=np.float32
        )
        weight = np.array([row[self.weight_key]], dtype=np.float32)
        eeg, cqf = self.apply_transform(eeg, cqf)

        data = dict(eeg_id=eeg_id, eeg=eeg, cqf=cqf, label=label, weight=weight)

        return data


class PerEegDataset(HmsBaseDataset):
    """
    EEG全体を1つずつロードする。
    """

    def __init__(
        self,
        metadata: pl.DataFrame,
        id2eeg: dict[int, np.ndarray],
        id2cqf: dict[int, np.ndarray],
        spec_id2spec: dict[int, np.ndarray] | None = None,
        duration: int = 2048,
        transform: BaseTransform | None = None,
        spec_duration_sec: int = 600,
        spec_sampling_rate: float = 0.5,
        spec_cropped_duration: int = 256,
        padding_type: str = "right",
        with_label: bool = True,
        weight_key: str = "weight_per_eeg",
        transform_enabled: bool = False,
        **kwdargs,
    ):
        metadata = metadata.group_by("eeg_id", maintain_order=True).agg(
            pl.col("spectrogram_id").first(),
            *[pl.col(f"{label}_vote_per_eeg").first() for label in LABELS],
            pl.col(weight_key).first(),
            *[pl.col(f"{label}_prob_per_eeg").first() for label in LABELS],
            pl.col("min_eeg_label_offset_sec").first(),
            pl.col("max_eeg_label_offset_sec").first(),
        )
        super().__init__(
            metadata,
            id2eeg,
            id2cqf,
            padding_type,
            duration,
            weight_key,
            spec_duration_sec=spec_duration_sec,
            spec_sampling_rate=spec_sampling_rate,
            spec_cropped_duration=spec_cropped_duration,
            transform_enabled=transform_enabled,
            transform=transform,
            with_label=with_label,
        )

        self.spec_id2spec = spec_id2spec
        self.spec_duration_sec = spec_duration_sec
        self.spec_sampling_rate = spec_sampling_rate
        self.spec_cropped_duration = spec_cropped_duration

        self.eeg_ids = sorted(self.metadata["eeg_id"].to_list())
        self.eeg_id2metadata = {
            row["eeg_id"]: row_to_dict(row, exclude_keys=["eeg_id"])
            for row in self.metadata.to_dicts()
        }

    def __len__(self):
        return len(self.eeg_ids)

    def __getitem__(self, idx):
        eeg_id = self.eeg_ids[idx]
        row = self.eeg_id2metadata[eeg_id]

        #
        # eeg & mask
        #
        eeg = self.id2eeg[eeg_id][: self.duration].astype(np.float32)
        cqf = self.id2cqf[eeg_id][: self.duration].astype(np.float32)

        eeg, cqf = pad_eeg(eeg, cqf, self.duration, self.padding_type)
        eeg, cqf = self.apply_transform(eeg, cqf)

        data = dict(eeg_id=eeg_id, eeg=eeg, cqf=cqf)

        #
        # spectrogram
        #
        if self.spec_id2spec is not None:
            spectrogram_id = row["spectrogram_id"]
            spec_start_frame = 0
            spec_end_frame = int(self.spec_duration_sec * self.spec_sampling_rate)
            bg_spec = self.spec_id2spec[spectrogram_id][
                :, spec_start_frame:spec_end_frame, :
            ].astype(np.float32)
            crop_frames = spec_end_frame - spec_start_frame - self.spec_cropped_duration

            if crop_frames > 0:
                crop_left = crop_frames // 2
                crop_right = crop_frames - crop_left
                bg_spec = bg_spec[:, crop_left:-crop_right, :]
                assert (
                    bg_spec.shape[1] == self.spec_cropped_duration
                ), f"spec shape mismatch: {bg_spec.shape}"

            data |= dict(bg_spec=bg_spec)

        #
        # label & weight
        #
        if self.with_label:
            label = np.array(
                [row[f"{label}_prob_per_eeg"] for label in LABELS], dtype=np.float32
            )
            weight = np.array([row[self.weight_key]], dtype=np.float32)
            data |= dict(label=label, weight=weight)

        return data


class PerEegSubsampleDataset(HmsBaseDataset):
    """
    ラベルに相当するEEGのchunkをランダムにサンプリングする。

    num_samples_per_eeg: 1 epoch中のEEGあたりのラベルのサンプル数
    """

    def __init__(
        self,
        metadata: pl.DataFrame,
        id2eeg: dict[int, np.ndarray],
        id2cqf: dict[int, np.ndarray],
        spec_id2spec: dict[int, np.ndarray] | None = None,
        sampling_rate: float = 40,
        duration_sec: int = 50,
        spec_duration_sec: int = 600,
        spec_sampling_rate: float = 0.5,
        spec_cropped_duration: int = 256,
        num_samples_per_eeg: int = 1,
        duration: int = 2048,
        transform: BaseTransform | None = None,
        with_label: bool = True,
        padding_type: str = "right",
        weight_key: str = "weight",
        seed: int = 42,
        transform_enabled: bool = False,
        **kwdargs,
    ):
        """
        spec_cropped_duration: 両端をcropしてこのサイズにする
        """
        metadata = metadata.select(
            "eeg_id",
            "spectrogram_id",
            *[f"{label}_prob" for label in LABELS],
            weight_key,
            "eeg_label_offset_seconds",
            "spectrogram_label_offset_seconds",
        )
        super().__init__(
            metadata,
            id2eeg,
            id2cqf,
            padding_type,
            duration,
            weight_key,
            sampling_rate=sampling_rate,
            duration_sec=duration_sec,
            num_samples_per_eeg=num_samples_per_eeg,
            seed=seed,
            spec_duration_sec=spec_duration_sec,
            spec_sampling_rate=spec_sampling_rate,
            spec_cropped_duration=spec_cropped_duration,
            transform_enabled=transform_enabled,
            transform=transform,
            with_label=with_label,
        )
        self.duration_sec = duration_sec
        self.sampling_rate = sampling_rate
        self.num_samples_per_eeg = num_samples_per_eeg
        self.eeg_ids = sorted(self.metadata["eeg_id"].unique().to_list())

        self.spec_id2spec = spec_id2spec
        self.spec_duration_sec = spec_duration_sec
        self.spec_sampling_rate = spec_sampling_rate
        self.spec_cropped_duration = spec_cropped_duration

        self.eeg_id2metadata = dict()
        for eeg_id, df in self.metadata.to_pandas().groupby("eeg_id"):
            self.eeg_id2metadata[eeg_id] = df.to_numpy()
        self.key2idx = {key: idx for idx, key in enumerate(self.metadata.columns)}

    def __len__(self):
        return len(self.eeg_ids) * self.num_samples_per_eeg

    def __getitem__(self, idx):
        #
        # sample label
        #
        eeg_id = self.eeg_ids[idx // self.num_samples_per_eeg]
        this_eeg = self.eeg_id2metadata[eeg_id]
        num_samples_in_this_eeg = len(this_eeg)
        sample_idx = torch.randint(
            num_samples_in_this_eeg, (1,), generator=self.generator
        ).item()
        row = this_eeg[sample_idx]

        #
        # eeg
        #
        eeg_label_offset_seconds = row[self.key2idx["eeg_label_offset_seconds"]]
        start_frame = int(eeg_label_offset_seconds * self.sampling_rate)
        end_frame = start_frame + int(self.duration_sec * self.sampling_rate)

        eeg = self.id2eeg[eeg_id][start_frame:end_frame].astype(np.float32)
        cqf = self.id2cqf[eeg_id][start_frame:end_frame].astype(np.float32)

        eeg, cqf = pad_eeg(
            eeg,
            cqf,
            self.duration,
            self.padding_type,
        )
        eeg, cqf = self.apply_transform(eeg, cqf)
        data = dict(eeg_id=eeg_id, eeg=eeg, cqf=cqf)

        #
        # spectrogram
        #
        if self.spec_id2spec is not None:
            spectrogram_id = row[self.key2idx["spectrogram_id"]]
            spectrogram_label_offset_seconds = row[
                self.key2idx["spectrogram_label_offset_seconds"]
            ]
            spec_start_frame = int(
                spectrogram_label_offset_seconds * self.spec_sampling_rate
            )
            spec_end_frame = spec_start_frame + int(
                self.spec_duration_sec * self.spec_sampling_rate
            )
            bg_spec = self.spec_id2spec[spectrogram_id][
                :, spec_start_frame:spec_end_frame, :
            ].astype(np.float32)
            crop_frames = spec_end_frame - spec_start_frame - self.spec_cropped_duration

            if crop_frames > 0:
                crop_left = crop_frames // 2
                crop_right = crop_frames - crop_left
                bg_spec = bg_spec[:, crop_left:-crop_right, :]
                assert (
                    bg_spec.shape[1] == self.spec_cropped_duration
                ), f"spec shape mismatch: {bg_spec.shape}"

            data |= dict(bg_spec=bg_spec)

        #
        # label & weight
        #
        if self.with_label:
            label = np.array(
                [row[self.key2idx[f"{label}_prob"]] for label in LABELS],
                dtype=np.float32,
            )
            weight = np.array([row[self.key2idx[self.weight_key]]], dtype=np.float32)
            data |= dict(label=label, weight=weight)

        return data


def get_train_loader(
    dataset: Dataset,
    batch_size: int,
    num_workers: int,
    pin_memory: bool = True,
    shuffle: bool = True,
    **kwargs,
):
    return DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=shuffle,
        num_workers=num_workers,
        pin_memory=pin_memory,
        drop_last=True,
        **kwargs,
    )


def get_valid_loader(
    dataset: Dataset,
    batch_size: int,
    num_workers: int,
    pin_memory: bool = True,
    **kwargs,
):
    return DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=False,
        num_workers=num_workers,
        pin_memory=pin_memory,
        drop_last=False,
        **kwargs,
    )
