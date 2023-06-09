import torch.nn as nn
import torch
from models.fgnn_model.layers import (
    ColumnAvgPooling,
    RegularBlock,
    ColumnMaxPooling,
    RowMaxPooling,
    Scaled_Block,
)


class Res_Scaled_Model(nn.Module):
    def __init__(
        self,
        original_features_num,
        num_blocks,
        in_features,
        out_features,
        depth_of_mlp,
        input_embed=True,
        ablation="",
        **kwargs,
    ):
        """
        take a batch of graphs (bs, n_vertices, n_vertices, in_features)
        and return a batch of graphs with new features
        graphs must have same size inside the batch
         - ablation : "", "rs", "in", or "rsin" (resp : nothing changed, removing residuals, removing InstanceNorms, removing both Residuals and InstanceNorms)
        """
        super().__init__()

        self.original_features_num = original_features_num
        self.num_blocks = num_blocks
        self.in_features = in_features
        self.out_features = out_features
        self.depth_of_mlp = depth_of_mlp
        self.embed = input_embed

        if ablation is None:
            ablation = ""
        self.use_residuals = not "rs" in ablation
        self.use_instancenorm = not "in" in ablation

        # First part - sequential mlp blocks
        if not self.embed:
            last_layer_features = self.original_features_num
        else:
            self.embedding = nn.Embedding(2, in_features)
            last_layer_features = self.in_features

        BlockClass = Scaled_Block if self.use_instancenorm else RegularBlock

        self.reg_blocks = nn.ModuleList()
        for i in range(self.num_blocks - 1):
            mlp_block = BlockClass(
                last_layer_features, in_features, self.depth_of_mlp, name=f"block_{i}"
            )
            self.reg_blocks.append(mlp_block)
            last_layer_features = in_features
        mlp_block = BlockClass(
            in_features, in_features, depth_of_mlp, name=f"block_{self.num_blocks-1}"
        )
        self.reg_blocks.append(mlp_block)
        self.last_mlp = nn.Conv2d(
            in_features, out_features, kernel_size=1, padding=0, bias=True
        )

    def forward(self, x):
        # here x.shape = (bs, n_vertices, n_vertices, n_features=original_features_num)
        if x.size(3) != self.original_features_num:
            print(
                "expected input feature {} and got {}".format(
                    self.original_features_num, x.shape[3]
                )
            )
            return
        # x = x.permute(0, 3, 1, 2)
        if self.embed:
            x = self.embedding(x[:, :, :, 1].long())
        x = x.permute(0, 3, 1, 2)
        # expects x.shape = (bs, n_features, n_vertices, n_vertices)
        # x.shape = (bs, n_features, n_vertices, _)
        for block in self.reg_blocks:
            if self.use_residuals:
                x = x + block(x)
            else:
                x = block(x)
        # return (bs, n_vertices, n_vertices, n_features=in_features)
        x = self.last_mlp(x)
        return x.permute(0, 2, 3, 1)


class RS_Node_Embedding(nn.Module):
    def __init__(
        self,
        original_features_num,
        num_blocks,
        in_features,
        out_features,
        depth_of_mlp,
        **kwargs,
    ):
        """
        take a batch of graphs (bs, n_vertices, n_vertices, in_features)
        and return a batch of node embedding (bs, n_vertices, out_features)
        graphs must have same size inside the batch
        """
        super().__init__()

        self.original_features_num = original_features_num
        self.num_blocks = num_blocks
        self.in_features = in_features
        self.out_features = out_features
        self.depth_of_mlp = depth_of_mlp
        self.base_model = Res_Scaled_Model(
            original_features_num,
            num_blocks,
            in_features,
            out_features,
            depth_of_mlp,
            **kwargs,
        )
        self.suffix = ColumnMaxPooling()

    def forward(self, x):
        x = self.base_model(x)
        x = self.suffix(x)
        return x


class RS_Edge_Embedding(nn.Module):
    def __init__(
        self,
        original_features_num,
        num_blocks,
        in_features,
        out_features,
        depth_of_mlp,
        **kwargs,
    ):
        """
        take a batch of graphs (bs, n_vertices, n_vertices, in_features)
        and return a batch of node embedding (bs, n_vertices, out_features)
        graphs must have same size inside the batch
        """
        super().__init__()

        self.original_features_num = original_features_num
        self.num_blocks = num_blocks
        self.in_features = in_features
        self.out_features = out_features
        self.depth_of_mlp = depth_of_mlp
        self.base_model = Res_Scaled_Model(
            original_features_num,
            num_blocks,
            in_features,
            out_features,
            depth_of_mlp,
            **kwargs,
        )

    def forward(self, x):
        x = self.base_model(x)
        return x


class RS_Graph_Embedding(nn.Module):
    def __init__(
        self,
        original_features_num,
        num_blocks,
        in_features,
        out_features,
        depth_of_mlp,
        **kwargs,
    ):
        """
        take a batch of graphs (bs, n_vertices, n_vertices, in_features)
        and return a batch of node embedding (bs, n_vertices, out_features)
        graphs must have same size inside the batch
        """
        super().__init__()

        self.original_features_num = original_features_num
        self.num_blocks = num_blocks
        self.in_features = in_features
        self.out_features = out_features
        self.depth_of_mlp = depth_of_mlp
        self.base_model = Res_Scaled_Model(
            original_features_num,
            num_blocks,
            in_features,
            out_features,
            depth_of_mlp,
            **kwargs,
        )
        new_kwargs = kwargs.copy()
        new_kwargs["input_embed"] = False
        self.edge_classif = nn.Linear(out_features, out_features)
        self.edge_pooling = ColumnAvgPooling()
        self.node_classif = nn.Linear(out_features, out_features)
        self.node_pooling = RowMaxPooling()
        self.graph_classif = nn.Linear(out_features, 1)

    def forward(self, x):
        x = self.base_model(x)
        x = self.edge_classif(x)
        x = torch.mean(x, dim=-2)  # self.edge_pooling(x)
        x = torch.sigmoid(x)
        if x.ndim == 2:  # if batch size is 1
            x = x.unsqueeze(0)
        x = self.node_classif(x)
        x = torch.mean(x, dim=-2)  # self.node_pooling(x)
        x = torch.sigmoid(x)
        x = self.graph_classif(x)
        return x
