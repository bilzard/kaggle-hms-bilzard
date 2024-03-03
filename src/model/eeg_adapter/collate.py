import torch
import torch.nn as nn
from einops import rearrange
from torch import Tensor


def dual_stack_eeg_channels(x: Tensor, drop_z: bool = False) -> Tensor:
    """
    spec: (b, 18, t)
    mask: (b, 18, t)

    Return:
    spec: (2, b, 10, t)
    mask: (2, b, 10, t)
    """
    ll = x[:, 0:4]
    lp = x[:, 4:8]
    z = x[:, 8:10]
    rp = x[:, 10:14]
    rl = x[:, 14:18]

    left = torch.cat([ll, lp], dim=1)
    right = torch.cat([rl, rp], dim=1)

    if not drop_z:
        left = torch.cat([left, z], dim=1)
        right = torch.cat([right, z], dim=1)

    x = torch.stack([left, right], dim=0)

    return x


class EegDualStackingCollator(nn.Module):
    """
    左右ごとに独立してencodingする
    """

    def __init__(self, drop_z: bool = False):
        super().__init__()
        self.drop_z = drop_z

    def forward(self, eeg: Tensor, eeg_mask: Tensor) -> tuple[Tensor, Tensor]:
        eeg = dual_stack_eeg_channels(eeg, drop_z=self.drop_z)
        eeg_mask = dual_stack_eeg_channels(eeg_mask, drop_z=self.drop_z)
        eeg = rearrange(eeg, "d b c t -> (d b) c t")
        eeg_mask = rearrange(eeg_mask, "d b c t -> (d b) c t")

        return eeg, eeg_mask


class EegDualPerChannelCollator(nn.Module):
    """
    左右、チャネルごとに独立してencodingする
    """

    def __init__(self, drop_z: bool = False):
        super().__init__()
        self.drop_z = drop_z

    def forward(self, eeg: Tensor, eeg_mask: Tensor) -> tuple[Tensor, Tensor]:
        eeg = dual_stack_eeg_channels(eeg, drop_z=self.drop_z)
        eeg_mask = dual_stack_eeg_channels(eeg_mask, drop_z=self.drop_z)
        eeg = rearrange(eeg, "d b c t -> (d c b) 1 t")
        eeg_mask = rearrange(eeg_mask, "d b c t -> (d c b) 1 t")

        return eeg, eeg_mask
