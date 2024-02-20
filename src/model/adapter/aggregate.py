import torch
import torch.nn as nn
from einops import rearrange
from torch import Tensor


def collate_lr_channels(spec: Tensor, mask: Tensor) -> tuple[Tensor, Tensor]:
    """
    左右のchannelをbatch方向に積み上げる
    Zチャネルは左右両方に入力する

    spec: (B, C, F, T)
    mask: (B, C, F, T)

    Return:
    spec: (2 * B, C, F, T)
    mask: (2 * B, C, F, T)
    """
    assert spec.shape[1] == 5

    spec_left = spec[:, [0, 1, 2], ...]
    spec_right = spec[:, [4, 3, 2], ...]
    spec = torch.cat([spec_left, spec_right], dim=0)

    mask_left = mask[:, [0, 1, 2], ...]
    mask_right = mask[:, [4, 3, 2], ...]
    mask = torch.cat([mask_left, mask_right], dim=0)

    return spec, mask


class WeightedMeanAggregator(nn.Module):
    def __init__(self, eps=1e-4):
        super().__init__()
        self.eps = eps

    def forward(
        self, spec: torch.Tensor, mask: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """
        spec: (B, 20, H, W)
        mask: (B, 19, H, W)

        return:
        specs: (B, 5, H, W)
        masks: (B, 5, H, W)
        """
        sum_specs = []
        sum_masks = []
        ranges = [0, 4, 8, 10, 14, 18]
        B, C, H, W = spec.shape
        for i, (start, end) in zip(range(C), zip(ranges[:-1], ranges[1:])):
            sum_spec = (spec[:, start:end] * mask[:, start:end]).sum(
                dim=1, keepdim=True
            )
            sum_mask = mask[:, start:end].sum(dim=1, keepdim=True)

            sum_specs.append(sum_spec / (sum_mask + self.eps))
            sum_masks.append(sum_mask)

        specs = torch.concat(sum_specs, dim=1)
        masks = torch.concat(sum_masks, dim=1)

        return specs, masks


class DualWeightedMeanAggregator(WeightedMeanAggregator):
    def forward(
        self, spec: torch.Tensor, mask: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor]:
        spec, mask = super().forward(spec, mask)

        return collate_lr_channels(spec, mask)


class TilingAggregator(nn.Module):
    """
    周波数方向にspetrogramを積み上げる
    """

    def __init__(self):
        super().__init__()

    def forward(
        self, spec: torch.Tensor, mask: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor]:
        tiled_specs = []
        tiled_masks = []
        ranges = [0, 4, 8, 10, 14, 18]
        B, C, F, T = spec.shape
        for i, (start, end) in zip(range(C), zip(ranges[:-1], ranges[1:])):
            ch = end - start
            pad_size = F * (4 - ch)
            tile = rearrange(spec[:, start:end], "b c f t -> b (c f) t", c=ch)
            tile = torch.nn.functional.pad(
                tile, (0, 0, 0, pad_size), mode="constant", value=0
            )
            tiled_specs.append(tile)

            mask = mask.expand(B, C, F, T)
            tiled_mask = rearrange(mask[:, start:end], "b c f t -> b (c f) t", c=ch)
            tiled_mask = torch.nn.functional.pad(
                tiled_mask, (0, 0, 0, pad_size), mode="constant", value=0
            )
            tiled_masks.append(tiled_mask)

        specs = torch.stack(tiled_specs, dim=1)
        masks = torch.stack(tiled_masks, dim=1)

        return specs, masks


class DualTilingAggregator(TilingAggregator):
    def forward(
        self, spec: torch.Tensor, mask: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor]:
        spec, mask = super().forward(spec, mask)

        return collate_lr_channels(spec, mask)


class FlatTilingAggregator(nn.Module):
    """
    周波数方向にspetrogramを積み上げる
    """

    def __init__(self):
        super().__init__()

    def forward(
        self, spec: torch.Tensor, mask: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor]:
        B, C, F, T = spec.shape
        spec = rearrange(spec, "b c f t -> b 1 (c f) t")

        mask = mask.expand(B, C, F, T)
        mask = rearrange(mask, "b c f t -> b 1 (c f) t")

        return spec, mask
