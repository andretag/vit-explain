import torch
from PIL import Image
import numpy
import sys
from torchvision import transforms
import numpy as np
import cv2
from compression.policies.vit_attention import softmax_normalize_att_mask

def rollout(attentions, discard_ratio, head_fusion):
    result = torch.eye(attentions[0].size(-1))
    with torch.no_grad():
        for attention in attentions:
            if head_fusion == "mean":
                attention_heads_fused = attention.mean(axis=1)
            elif head_fusion == "max":
                attention_heads_fused = attention.max(axis=1)[0]
            elif head_fusion == "min":
                attention_heads_fused = attention.min(axis=1)[0]
            else:
                raise "Attention head fusion type Not supported"

            # Drop the lowest attentions, but
            # don't drop the class token
            flat = attention_heads_fused.view(attention_heads_fused.size(0), -1)
            _, indices = flat.topk(int(flat.size(-1)*discard_ratio), -1, False, sorted=True)
            print(f"VIT explain indices:\n{indices}")
            indices = indices[indices != 0]
            flat[:, indices] = 0

            I = torch.eye(attention_heads_fused.size(-1))
            a = (attention_heads_fused + I)/2
            print(f"VIT explain a:\n{a[0, :]}")
            a = a / np.clip(a = a.sum(dim=-1), a_min=1e-12, a_max=None)

            result = torch.matmul(a, result)
            print(f"VIT explain result:\n{result[0, :]}")
    
    # TODO: why divide by max???
    # Look at the total attention between the class token,
    # and the image patches
    mask = result[0, 0 , 1 :]
    # In case of 224x224 image, this brings us from 196 to 14
    width = int(mask.size(-1)**0.5)
    mask = mask.reshape(width, width).numpy()
    mask = mask / np.clip(a = np.max(mask), a_min=1e-12, a_max=None)
    return mask    

class VITAttentionRollout:
    def __init__(self, model, attention_layer_name='attn_drop', head_fusion="mean",
        discard_ratio=0.7):
        self.model = model
        self.head_fusion = head_fusion
        self.discard_ratio = discard_ratio
        for name, module in self.model.named_modules():
            if attention_layer_name in name:
                module.register_forward_hook(self.get_attention)

        self.attentions = []

    def get_attention(self, module, input, output):
        self.attentions.append(output.cpu())

    def __call__(self, input_tensor):
        self.attentions = []
        with torch.no_grad():
            output = self.model(input_tensor)
        #print("Accumulated attentions: ")
        #print(self.attentions)

        return rollout(self.attentions, self.discard_ratio, self.head_fusion)