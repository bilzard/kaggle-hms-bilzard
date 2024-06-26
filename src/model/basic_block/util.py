import torch.nn.functional as F
from torch import Tensor


def calc_similarity(x: Tensor, y: Tensor, channel_dim: int = 1, eps=1e-4) -> Tensor:
    """
    x: (B, C, F, T)
    y: (B, C, F, T)

    Returns:
    similarity: (B, 1, F, T)
    """

    return F.cosine_similarity(x, y, dim=channel_dim, eps=eps).unsqueeze(channel_dim)


def vector_pair_mapping(
    x: Tensor, y: Tensor, base_type="diff-mean"
) -> tuple[Tensor, Tensor]:
    match base_type:
        case "diff-mean":
            u = (x - y).abs()
            v = (x + y) / 2
        case "prod-sum":
            u = x + y
            v = x * y
        case "max-min":
            u = x.min(y)
            v = x.max(y)
        case "identity":
            u = x
            v = y
        case _:
            raise ValueError(f"Invalid base_type: {base_type}")
    return u, v


def norm_mean_std(x: Tensor, dim: tuple[int, ...], eps: float = 1e-4) -> Tensor:
    mean = x.mean(dim=dim, keepdim=True)
    std = x.std(dim=dim, keepdim=True)
    return (x - mean) / std.clamp_min(eps)
