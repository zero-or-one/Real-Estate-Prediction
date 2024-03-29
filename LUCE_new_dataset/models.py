import torch.nn as nn
import torch
from torch.nn.parameter import Parameter
import torch.nn.functional as F
import math

"""
GCN layer: Accept all HIN adjacency matrices (meta_size * Nodes * Nodes),
        And all feature matrix X (Nodes * input_dim)
Convert Nodes LSTM embeddings in each month into graph embeddings
The output is graph embedding of all data: Nodes * output_dim
"""


class GraphConvolution(nn.Module):
    def __init__(self, in_features, out_features, bias=True):
        super(GraphConvolution, self).__init__()
        self.in_features = in_features
        self.out_features = out_features
        self.weight = Parameter(torch.FloatTensor(in_features, out_features))
        if bias:
            self.bias = Parameter(torch.FloatTensor(out_features))
        else:
            self.register_parameter('bias', None)
        self.reset_parameters()

    def reset_parameters(self):
        stdv = 1. / math.sqrt(self.weight.size(1))
        self.weight.data.uniform_(-stdv, stdv)
        if self.bias is not None:
            self.bias.data.uniform_(-stdv, stdv)

    def forward(self, input, adj):
        support = torch.mm(input.float(), self.weight.float())
        adj = adj + torch.eye(adj.shape[0],adj.shape[0]).to(input.device).float()  # A+I
        #print(adj.type(), support.type())
        #print(adj.shape, support.shape)
        output = torch.spmm(adj.float(), support)
        if self.bias is not None:
            return output + self.bias
        else:
            return output

    def __repr__(self):
        return self.__class__.__name__ + ' (' \
               + str(self.in_features) + ' -> ' \
               + str(self.out_features) + ')'


class GCN2lv(nn.Module):
    def __init__(self, nfeat, gc1_outdim, gc2_outdim, dropout, meta_size):
        super(GCN2lv, self).__init__()
        self.meta_size = meta_size
        self.gc1_outdim = gc1_outdim
        self.gc2_outdim = gc2_outdim
        # 用Variable引入权重
        self.W = Parameter(torch.FloatTensor(self.meta_size, 1))
        nn.init.xavier_uniform_(self.W.data)

        self.gc1 = GraphConvolution(nfeat, gc1_outdim)
        self.gc2 = GraphConvolution(gc1_outdim, gc2_outdim)
        self.dropout = dropout

    def forward(self, adj, x):
        # Each meta-graph is passed to GCN separately
        gcn_out = []
        shape = x.shape[0]
        for i in range(self.meta_size):
            gcn_out.append(F.relu(self.gc1(x, adj[i])))
            gcn_out[i] = F.relu(self.gc2(gcn_out[i], adj[i]))
            gcn_out[i] = gcn_out[i].view(1,shape*self.gc2_outdim)

        x = gcn_out[0]
        for i in range(1, self.meta_size):
            x = torch.cat((x, gcn_out[i]), 0)
        x = torch.t(x)
        # print(self.W)
        x = F.relu(torch.mm(x, self.W))
        x = x.view(shape, self.gc2_outdim)
        x = F.dropout(x,  self.dropout, training=self.training)
        return x


# Public LSTM version
class r_gcn2lv_1LSTMs(nn.Module):
    def __init__(self, gcn_input_dim, gc1_out_dim, lstm_input_dim, hidden_dim,
                 label_out_dim, meta_size, all_month, month_len, layers=1, dropout=0.2):
        super(r_gcn2lv_1LSTMs, self).__init__()
        self.hidden_dim = hidden_dim
        self.meta_size = meta_size
        self.all_month = all_month
        self.month_len = month_len
        self.glstm_list = []
        
        for i in range(month_len):
            self.glstm_list.append(GCN2lv(nfeat=gcn_input_dim, gc1_outdim=gc1_out_dim, gc2_outdim=lstm_input_dim,
                                          dropout=dropout, meta_size=meta_size))
        self.glstm = nn.ModuleList(self.glstm_list)
        
        #self.glstm = GCN2lv(nfeat=gcn_input_dim, gc1_outdim=gc1_out_dim, gc2_outdim=lstm_input_dim,
        #                    dropout=dropout, meta_size=meta_size)
        self.lstm = nn.LSTM(input_size=lstm_input_dim, hidden_size=self.hidden_dim, num_layers=layers)
        # self.linear_gcn = nn.Linear(hidden_dim, gcn_input_dim)  # 暂时输入输入维度一致，后续可再调整
        self.linear_price = nn.Linear(gcn_input_dim, label_out_dim)
        self.LeakyReLU = nn.LeakyReLU(0.2)

    def forward(self, adj, x, y_index):
        """
        :param x: Nodes * input_dim
        :param adj: meta_size * Nodes * Nodes
        :param y_index: last_month(1) * batch_size
        :return: Global features and the price of the last month
        """
        Nodes, num_features = x.size()
        month_len, batch_size = y_index.size()
        #print('y_index: ' + str(y_index.shape))
        #print('x'+str(x.size()))
        #print(self.all_month, self.month_len)
        #exit()
        
        # print('month_len: '+ str(month_len))
        house_size = int(Nodes / self.all_month)
        out_allmonth = x
        for i in range(0, self.month_len):
            g_emb = self.glstm[i](adj, out_allmonth)  # Nodes * lstm_input_dim
            # print('g_emb: ' + str(g_emb.shape))
            # Split g_emb into full-length time series
            seq_list = []
            for i in range(self.all_month):
                seq_list.append(
                    g_emb.index_select(0, torch.LongTensor(range(i * house_size, (i + 1) * house_size)).to(x.device)))  # 0按行，1按列
            sequence = torch.stack(seq_list, 0)  # month_len, batch_size, lstm_input_dim
            # print('sequence: ' + str(sequence.shape))
            # Put all the embeddings generated by GCN into LSTM training
            out, hidden = self.lstm(sequence)  # out:(month_len, house_size, hidden_size)
            # print('out: ' + str(out.shape))
            out_allmonth_t = out.view(Nodes, self.hidden_dim)  #  Nodes*LSTM_hidden_size
            # print('out_allmonth_t: ' + str(out_allmonth_t.shape))
            # out_allmonth = self.linear_gcn(out_allmonth_t)  # Output 1: embedding of all houses
            out_price_t = self.linear_price(out_allmonth_t)
            # Take out the label of the house where the transaction occurred, and use it as a signal for backpropagation
             # It depends entirely on the length of y_index, which months are included in y_index, and the label of which months is taken
            label_list = []
            for i in range(month_len):
                label_list.append(out_price_t.index_select(0, y_index[i]))
            out_price = torch.stack(label_list, 0)  # Output 2: label of the house participating in the transaction this month
        return out_allmonth, self.LeakyReLU(out_price)


class GCN2lv_static(nn.Module):
    def __init__(self, config):
        super(GCN2lv_static, self).__init__()
        self.meta_size = config.meta_size
        self.gc1_outdim = config.gc1_outdim
        self.gc2_outdim = config.gc2_outdim
        # Weight is introduced with Parameter
        self.W = Parameter(torch.FloatTensor(self.meta_size, 1))
        nn.init.xavier_uniform_(self.W.data)
        self.gc1 = GraphConvolution(config.nfeat, config.gc1_outdim)
        self.gc2 = GraphConvolution(config.gc1_outdim, config.gc2_outdim)
        #self.gc3 = GraphConvolution(config.gc2_outdim, config.gc2_outdim)
        self.dropout = config.dropout
        self.dense2 = nn.Linear(config.gc2_outdim, 1)

    def forward(self, x, adj):
        # Pass each meta-graph into GCN separately
        gcn_out = []
        shape = x.shape[0]
        for i in range(self.meta_size):
            gcn_out.append(F.relu(self.gc1(x, adj[i])))
            gcn_out[i] = F.relu(self.gc2(gcn_out[i], adj[i]))
            #gcn_out[i] = F.relu(self.gc3(gcn_out[i], adj[i]))
            gcn_out[i] = gcn_out[i].view(1,shape*self.gc2_outdim)

        x = gcn_out[0]
        for i in range(1, self.meta_size):
            x = torch.cat((x, gcn_out[i]), 0)
        x = torch.t(x)
        x = F.relu(torch.mm(x, self.W))
        # print(self.W,flush=True)
        x = x.view(shape,self.gc2_outdim)
        x = F.dropout(x, self.dropout, training=self.training)
        x = self.dense2(x)
        return x


class GCNlstm_static(nn.Module):
    def __init__(self, config):
        super(GCNlstm_static, self).__init__()
        self.meta_size = config.meta_size
        self.gc1_outdim = config.gc1_outdim
        self.gc2_outdim = config.gc2_outdim
        self.house_size = config.house_size
        # Use Parameter to introduce weights
        self.W = Parameter(torch.FloatTensor(self.meta_size, 1))
        nn.init.xavier_uniform_(self.W.data)

        self.gc1 = GraphConvolution(config.nfeat, config.gc1_outdim)
        self.gc2 = GraphConvolution(self.gc1_outdim, self.gc2_outdim)
        self.lstm = nn.LSTM(input_size=self.gc2_outdim, hidden_size=self.gc2_outdim, num_layers=1)
        self.LeakyReLU = nn.LeakyReLU(0.2)
        self.dropout = config.dropout
        self.linear_price = nn.Linear(self.gc2_outdim, 1)

    def forward(self, x, adj):
        # Pass each meta-graph into GCN separately
        gcn_out = []
        shape = x.shape[0]
        house_size = self.house_size
        seq_len = int(x.shape[0]/house_size)
        for i in range(self.meta_size):
            gcn_out.append(F.relu(self.gc1(x, adj[i])))
            gcn_out[i] = F.relu(self.gc2(gcn_out[i], adj[i]))
            gcn_out[i] = gcn_out[i].view(1, shape*self.gc2_outdim)

        x = gcn_out[0]
        for i in range(1, self.meta_size):
            x = torch.cat((x, gcn_out[i]), 0)
        x = torch.t(x)
        x = F.relu(torch.mm(x, self.W))
        # print(self.W,flush=True)
        x = x.view(shape, self.gc2_outdim)
        x = F.dropout(x, self.dropout, training=self.training)
        seq_list = []
        for i in range(seq_len):
            seq_list.append(
                x.index_select(0, torch.LongTensor(range(i * house_size, (i + 1) * house_size)).to(x.device)))  # 0 by row, 1 by column
        sequence = torch.stack(seq_list, 0)  # month_len, batch_size, lstm_input_dim
        # print('sequence: ' + str(sequence.shape))
        # LSTM training on all embeddings generated by GCN
        out, hidden = self.lstm(sequence)  # out:(month_len, batch_size, hidden_size)
        out = out.view(shape, self.gc2_outdim)
        x = self.linear_price(out)
        return x



#  Define T-GCN model
class T_GCN(nn.Module):
    def __init__(self, config):
        super(T_GCN, self).__init__()
        self.meta_size = config.meta_size
        self.gc1_outdim = config.gc1_outdim
        self.gc2_outdim = config.gc2_outdim
        self.house_size = config.house_size
        # 用Parameter引入权重 Use Parameter to introduce weights
        self.W = Parameter(torch.FloatTensor(self.meta_size, 1))
        nn.init.xavier_uniform_(self.W.data)
        self.gc1 = GraphConvolution(config.nfeat, config.gc1_outdim)
        self.gc2 = GraphConvolution(config.gc1_outdim, config.gc2_outdim)
        # GRU introduction
        # The input_size here is the dimension of the word vector, 
        # hidden_size is the dimension of the hidden layer, n_layers is the number of layers of the GRU
        self.gru = nn.GRU(input_size=config.gc2_outdim, hidden_size=config.gc2_outdim, num_layers=1)
        self.LeakyReLU = nn.LeakyReLU(0.2)
        self.dropout = config.dropout
        self.linear_price = nn.Linear(self.gc2_outdim, 1)

    def forward(self, adj, x):
        # Pass each meta-graph into GCN separately
        gcn_out = []
        shape = x.shape[0]
        house_size = self.house_size
        seq_len = int(x.shape[0]/house_size)
        for i in range(self.meta_size):
            gcn_out.append(F.relu(self.gc1(x, adj[i])))
            gcn_out[i] = F.relu(self.gc2(gcn_out[i], adj[i]))
            gcn_out[i] = gcn_out[i].view(1, shape*self.gc2_outdim)

        x = gcn_out[0]
        for i in range(1, self.meta_size):
            x = torch.cat((x, gcn_out[i]), 0)
        x = torch.t(x)
        x = F.relu(torch.mm(x, self.W))
        # print(self.W,flush=True)
        x = x.view(shape, self.gc2_outdim)
        x = F.dropout(x, self.dropout, training=self.training)

        seq_list = []
        for i in range(seq_len):
            seq_list.append(
                x.index_select(0, torch.LongTensor(range(i * house_size, (i + 1) * house_size)).to(x.device)))  # 0 by row, 1 by column
        sequence = torch.stack(seq_list, 0)  # month_len, batch_size, lstm_input_dim
        # print('sequence: ' + str(sequence.shape))
        # LSTM training on all embeddings generated by GCN
        out, hidden = self.gru(sequence)
        # out:(month_len, batch_size, hidden_size)
        out = out.view(shape, self.gc2_outdim)
        x = self.linear_price(out)
        return x



class LSTM_static(nn.Module):
    def __init__(self, config):
        super(LSTM_static, self).__init__()
        self.house_size = config.house_size
        self.nfeat = config.nfeat
        self.lstm = nn.LSTM(input_size=self.nfeat, hidden_size=self.nfeat, num_layers=config.num_layers, bidirectional=config.bidirectional)
        self.LeakyReLU = nn.LeakyReLU(0.2)
        self.dropout = config.dropout
        self.linear_price = nn.Linear(2*self.nfeat, 1)

    def forward(self, x):
        shape = x.shape[0]
        house_size = self.house_size
        seq_len = int(shape/house_size)
        # Construct time series
        seq_list = []
        for i in range(seq_len):
            seq_list.append(
                x.index_select(0, torch.LongTensor(range(i * house_size, (i + 1) * house_size)).to(x.device)))  # 0 by row, 1 by column
        sequence = torch.stack(seq_list, 0)  # month_len, batch_size, lstm_input_dim
        # LSTM training on all embeddings generated by GCN
        #print(sequence.shape)
        out, hidden = self.lstm(sequence)  # out:(month_len, batch_size, hidden_size)
        #print(out.shape, self.nfeat)
        out = out.view(shape, self.nfeat)
        x = self.linear_price(out)
        return x 

class LSTM(nn.Module):
    def __init__(self, config):
        super(LSTM, self).__init__()
        self.hidden_dim = config.hidden_dim
        self.num_layers = config.num_layers
        self.output_dim = 1
        self.dimension = self.num_layers * 2 if config.bidirectional else self.num_layers
        self.lstm = nn.LSTM(config.input_dim, config.hidden_dim, config.num_layers, batch_first=True,\
         dropout=config.dropout, bidirectional=config.bidirectional)
        fc_input_dim = self.hidden_dim * 2 if config.bidirectional else self.hidden_dim
        self.fc = nn.Linear(fc_input_dim, self.output_dim)

    def forward(self, x):
        x = x.unsqueeze(0)
        
        h0 = torch.zeros(self.dimension, x.size(0), self.hidden_dim).requires_grad_().to(x.device)
        c0 = torch.zeros(self.dimension, x.size(0), self.hidden_dim).requires_grad_().to(x.device)
        out, (hn, cn) = self.lstm(x, (h0.detach(), c0.detach()))
        out = self.fc(out) 

        return out.squeeze(0)