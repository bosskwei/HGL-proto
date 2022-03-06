import time
import torch
import sageir
import dgl as dgl
from sageir import mp, utils
from dgl.data import rdf, reddit
from dgl.data import citation_graph as cit
from dgl.data import gnn_benchmark as bench
from torch_geometric import datasets as pygds
from common.model import GCNModel, GATModel, RGCNModel, RGATModel
from common.dglmodel import DGLGCNModel, DGLGATModel, DGLRGCNModel, DGLRGATModel
from common.pygmodel import PyGGCNModel, PyGGATModel, PyGRGCNModel, PyGRGATModel


class BenchMethods:
    @staticmethod
    def _check_dataset(dataset):
        # dataset
        divider = 10 * '-'
        print('{}[{}]{}'.format(
            divider, dataset.name, divider
        ))
        graph: dgl.DGLGraph = dataset[0]
        print('n_nodes:', graph.num_nodes())
        #
        if graph.is_homogeneous:
            avg_degrees = torch.mean(
                graph.in_degrees().type(
                    torch.FloatTensor
                )
            ).item()
            print('n_edges:', graph.num_edges())
            print('avg_degrees:', avg_degrees)
        else:
            n_rows = 0
            n_edges = 0
            avg_degrees = []
            print(
                'meta-paths:',
                len(graph.canonical_etypes)
            )
            for sty, ety, dty in graph.canonical_etypes:
                avg_degrees.append(
                    torch.mean(
                        graph.in_degrees(
                            etype=(sty, ety, dty)
                        ).type(
                            torch.FloatTensor
                        )
                    ).item()
                )
                n_rows += graph.num_dst_nodes(dty)
                n_edges += graph.num_edges((sty, ety, dty))
            print('n_rows:', n_rows)
            print('n_edges:', n_edges)
            avg_degrees = sum(avg_degrees) / len(avg_degrees)
            print('avg_degrees:', avg_degrees)

    @staticmethod
    def _bench_pyg_homo(dataset, model, d_hidden):
        # info
        print('[PYG] {}, {}, d_hidden={}'.format(
            dataset.name, model.__name__, d_hidden
        ))

        # dataset
        n_epochs = 20
        graph = dataset[0].to('cuda')
        n_nodes = graph.num_nodes
        print('n_nodes:', n_nodes)
        n_edges = graph.num_edges
        print('n_edges:', n_edges)
        n_labels = dataset.num_classes
        print('n_labels:', n_labels)
        n_features = graph.num_features
        print('n_features:', n_features)

        # inputs
        gradient = torch.ones(
            [n_nodes, n_labels]
        ).to('cuda')
        model = model(
            in_features=n_features,
            gnn_features=d_hidden,
            out_features=n_labels
        ).to('cuda')

        # prewarm
        y = model(graph)
        y.backward(gradient=gradient)
        torch.cuda.synchronize()

        # training
        timing = None
        time.sleep(2.0)
        print('[TRAINING]')
        with utils.Profiler(n_epochs) as prof:
            for _ in range(n_epochs):
                y = model(graph)
                y.backward(gradient=gradient)
            torch.cuda.synchronize()
            timing = prof.timing() / n_epochs
        print('throughput: {:.1f}'.format(n_edges / timing))

    @staticmethod
    def _bench_pyg_hetero(dataset, model, d_hidden):
        # info
        if hasattr(dataset, 'name'):
            name = dataset.name
        else:
            name = type(dataset).__name__
        print('[PYG] {}, {}, d_hidden={}'.format(
            name, model.__name__, d_hidden
        ))

        # dataset
        n_epochs = 20
        graph = dataset[0].to('cuda')
        n_edges = graph.num_edges
        print('n_edges:', n_edges)
        assert len(graph.node_types) == 1
        nty = graph.node_types[0]
        n_labels = torch.max(
            graph[nty]['train_y']
        ).item() + 1
        print('n_labels:', n_labels)

        # inputs
        gradient = torch.ones([
            graph[nty].num_nodes,
            n_labels
        ]).to('cuda')
        model = model(
            graph=graph,
            in_features=d_hidden,
            gnn_features=d_hidden,
            out_features=n_labels
        ).to('cuda')

        # prewarm
        y = model(graph)[nty]
        y.backward(gradient=gradient)
        torch.cuda.synchronize()

        # training
        timing = None
        time.sleep(2.0)
        print('[TRAINING]')
        with utils.Profiler(n_epochs) as prof:
            for _ in range(n_epochs):
                y = model(graph)[nty]
                y.backward(gradient=gradient)
            torch.cuda.synchronize()
            timing = prof.timing() / n_epochs
        print('throughput: {:.1f}'.format(n_edges / timing))

    @staticmethod
    def _bench_dgl_homo(dataset, model, d_hidden):
        # info
        print('[DGL] {}, {}, d_hidden={}'.format(
            dataset.name, model.__name__, d_hidden
        ))

        # dataset
        n_epochs = 20
        graph = dataset[0].to('cuda')
        n_nodes = graph.num_nodes()
        print('n_nodes:', n_nodes)
        n_edges = graph.num_edges()
        print('n_edges:', n_edges)
        n_labels = dataset.num_classes
        print('n_labels:', n_labels)
        feature = graph.ndata.pop(
            'feat'
        ).to('cuda')
        n_features = feature.size(-1)
        print('n_features:', n_features)

        # inputs
        gradient = torch.ones(
            [n_nodes, n_labels]
        ).to('cuda')
        model = model(
            in_features=n_features,
            gnn_features=d_hidden,
            out_features=n_labels
        ).to('cuda')

        # prewarm
        y = model(graph, feature)
        y.backward(gradient=gradient)
        torch.cuda.synchronize()

        # training
        timing = None
        time.sleep(2.0)
        print('[TRAINING]')
        with utils.Profiler(n_epochs) as prof:
            for _ in range(n_epochs):
                y = model(graph, feature)
                y.backward(gradient=gradient)
            torch.cuda.synchronize()
            timing = prof.timing() / n_epochs
        print('throughput: {:.1f}'.format(n_edges / timing))

    @staticmethod
    def _bench_dgl_hetero(dataset, model, d_hidden):
        # info
        print('[DGL] {}, {}, d_hidden={}'.format(
            dataset.name, model.__name__, d_hidden
        ))

        # dataset
        n_epochs = 20
        graph = dataset[0].to('cuda')
        n_edges = graph.num_edges()
        print('n_edges:', n_edges)
        n_labels = dataset.num_classes
        print('n_labels:', n_labels)
        category = dataset.predict_category
        print('predict_category:', category)

        # inputs
        gradient = torch.ones([
            graph.num_nodes(category),
            n_labels
        ]).to('cuda')
        model = model(
            g=graph,
            in_features=d_hidden,
            gnn_features=d_hidden,
            out_features=n_labels
        ).to('cuda')

        # prewarm
        y = model(graph)[category]
        y.backward(gradient=gradient)
        torch.cuda.synchronize()

        # training
        timing = None
        time.sleep(2.0)
        print('[TRAINING]')
        with utils.Profiler(n_epochs) as prof:
            for _ in range(n_epochs):
                y = model(graph)[category]
                y.backward(gradient=gradient)
            torch.cuda.synchronize()
            timing = prof.timing() / n_epochs
        print('throughput: {:.1f}'.format(n_edges / timing))

    @staticmethod
    def _bench_sageir_homo(dataset, model, d_hidden):
        # info
        print('[SAGEIR] {}, {}, d_hidden={}'.format(
            type(dataset).__name__,
            model.__name__, d_hidden
        ))

        # dataset
        n_epochs = 20
        dglgraph = dataset[0].to('cuda')
        graph = mp.from_dglgraph(dglgraph)
        n_nodes = dglgraph.num_nodes()
        print('n_nodes:', n_nodes)
        n_edges = dglgraph.num_edges()
        print('n_edges:', n_edges)
        n_labels = dataset.num_classes
        print('n_labels:', n_labels)
        feature = dglgraph.ndata.pop('feat')
        n_features = feature.size(-1)
        print('n_features:', n_features)

        # inputs
        feature = torch.randn(
            size=[n_nodes, n_features]
        ).to('cuda')
        gradient = torch.ones(
            [n_nodes, n_labels]
        ).to('cuda')
        model = model(
            in_features=n_features,
            gnn_features=d_hidden,
            out_features=n_labels
        ).to('cuda')
        kwargs = dict({
            'graph': graph, 'x': feature
        })
        if isinstance(model, GCNModel):
            kwargs['norm'] = graph.right_norm()

        # optimizer
        mod2ir = sageir.Module2IR()
        optimizer = sageir.Optimizer()
        dataflow = mod2ir.transform(
            model, kwargs=kwargs
        )
        dataflow = optimizer.lower(
            dataflow, kwargs=kwargs
        )
        executor = sageir.Executor()

        # prewarm
        executor.train()
        y = executor.run(
            dataflow, kwargs=kwargs
        )
        y.backward(gradient=gradient)
        torch.cuda.synchronize()

        # training
        timing = None
        time.sleep(2.0)
        print('[TRAINING]')
        with utils.Profiler(n_epochs) as prof:
            for _ in range(n_epochs):
                y = executor.run(
                    dataflow, kwargs=kwargs
                )
                y.backward(gradient=gradient)
            torch.cuda.synchronize()
            timing = prof.timing() / n_epochs
        print('throughput: {:.1f}'.format(n_edges / timing))

    @staticmethod
    def _bench_sageir_hetero(dataset, model, d_hidden):
        # info
        print('[SAGEIR] {}, {}, d_hidden={}'.format(
            type(dataset).__name__,
            model.__name__, d_hidden
        ))

        # dataset
        n_epochs = 20
        dglgraph = dataset[0].to('cuda')
        graph = mp.from_dglgraph(dglgraph)
        n_edges = dglgraph.num_edges()
        print('n_edges:', n_edges)
        n_labels = dataset.num_classes
        print('n_labels:', n_labels)
        category = dataset.predict_category
        print('predict_category:', category)

        # inputs
        gradient = torch.ones([
            dglgraph.num_nodes(category),
            n_labels
        ]).to('cuda')
        model = model(
            hgraph=graph,
            in_features=d_hidden,
            gnn_features=d_hidden,
            out_features=n_labels
        ).to('cuda')
        node_indices = {
            nty: torch.linspace(
                0, num - 1, num,
                dtype=torch.int64
            ).to('cuda')
            for nty, num in graph.nty2num.items()
        }
        kwargs = dict({
            'hgraph': graph,
            'xs': node_indices
        })
        if isinstance(model, RGCNModel):
            kwargs['norms'] = {
                rel: g.right_norm()
                for rel, g in graph.hetero_graph.items()
            }

        # optimizer
        mod2ir = sageir.Module2IR()
        optimizer = sageir.Optimizer()
        stitcher = sageir.Stitcher()
        dataflow = mod2ir.transform(
            model, kwargs=kwargs
        )[category]
        dataflow = optimizer.lower(
            dataflow, kwargs=kwargs
        )
        dataflow = stitcher.transform(
            dataflow, kwargs=kwargs
        )
        executor = sageir.Executor()

        # prewarm
        executor.train()
        y = executor.run(
            dataflow, kwargs=kwargs
        )
        y.backward(gradient=gradient)
        torch.cuda.synchronize()

        # training
        timing = None
        time.sleep(2.0)
        print('[TRAINING]')
        with utils.Profiler(n_epochs) as prof:
            for _ in range(n_epochs):
                y = executor.run(
                    dataflow, kwargs=kwargs
                )
                y.backward(gradient=gradient)
            torch.cuda.synchronize()
            timing = prof.timing() / n_epochs
        print('throughput: {:.1f}'.format(n_edges / timing))


class Benchmark(BenchMethods):
    HOM_MODELS = [
        (PyGGCNModel, DGLGCNModel, GCNModel),
        (PyGGATModel, DGLGATModel, GATModel),
    ]
    HET_MODELS = [
        (PyGRGCNModel, DGLRGCNModel, RGCNModel),
        (PyGRGATModel, DGLRGATModel, RGATModel),
    ]
    HOM_DATASETS = [
        'cora_tiny', 'amazon', 'cora_full', 'reddit',
    ]
    HET_DATASETS = [
        'aifb_hetero', 'mutag_hetero', 'bgs_hetero', 'am_hetero'
    ]
    DGL_DATASETS = {
        'cora_tiny': cit.CoraGraphDataset,  # 2.7k
        'amazon': bench.AmazonCoBuyPhotoDataset,  # 7.7k
        'cora_full': bench.CoraFullDataset,  # 19.8k
        'reddit': reddit.RedditDataset,  # 233.0k
        #
        'aifb_hetero': rdf.AIFBDataset,  # 7.3k
        'mutag_hetero': rdf.MUTAGDataset,  # 27.2k
        'bgs_hetero': rdf.BGSDataset,  # 94.8k
        'am_hetero': rdf.AMDataset  # 881.7k
    }
    PYG_DATASETS = {
        'cora_tiny': lambda: pygds.Planetoid(root='.data', name='Cora'),
        'amazon': lambda: pygds.Amazon(root='.data', name='Photo'),
        'cora_full': lambda: pygds.CoraFull(root='.data'),
        'reddit': lambda: pygds.Reddit(root='.data'),
        #
        'aifb_hetero': lambda: pygds.Entities(root='.data', name='AIFB', hetero=True),
        'mutag_hetero': lambda: pygds.Entities(root='.data', name='MUTAG', hetero=True),
        'bgs_hetero': lambda: pygds.Entities(root='.data', name='BGS', hetero=True),
        'am_hetero': lambda: pygds.Entities(root='.data', name='AM', hetero=True),
    }

    def dataset_info(self):
        for dataset in self.HOM_DATASETS:
            dataset = self.DGL_DATASETS[
                dataset
            ](verbose=False)
            self._check_dataset(dataset)
        for dataset in self.HET_DATASETS:
            dataset = self.DGL_DATASETS[
                dataset
            ](verbose=False)
            self._check_dataset(dataset)

    def bench_homogenous(self):
        for name in self.HOM_DATASETS:
            for pyg_model, dgl_model, sageir_model in \
                    self.HOM_MODELS:
                for d_hidden in [16]:
                    #
                    dataset = self.PYG_DATASETS[
                        name
                    ]()
                    time.sleep(2.0)
                    self._bench_pyg_homo(
                        dataset=dataset,
                        model=pyg_model,
                        d_hidden=d_hidden
                    )
                    #
                    dataset = self.DGL_DATASETS[
                        name
                    ](verbose=False)
                    time.sleep(2.0)
                    self._bench_dgl_homo(
                        dataset=dataset,
                        model=dgl_model,
                        d_hidden=d_hidden,
                    )
                    time.sleep(2.0)
                    self._bench_sageir_homo(
                        dataset=dataset,
                        model=sageir_model,
                        d_hidden=d_hidden,
                    )
                    return

    def bench_heterogenous(self):
        for name in self.HET_DATASETS:
            for pyg_model, dgl_model, sageir_model in \
                    self.HET_MODELS:
                for d_hidden in [16]:
                    #
                    dataset = self.PYG_DATASETS[
                        name
                    ]()
                    self._bench_pyg_hetero(
                        dataset=dataset,
                        model=pyg_model,
                        d_hidden=d_hidden
                    )
                    #
                    dataset = self.DGL_DATASETS[
                        name
                    ](verbose=False)
                    self._bench_dgl_hetero(
                        dataset=dataset,
                        model=dgl_model,
                        d_hidden=d_hidden,
                    )
                    time.sleep(2.0)
                    self._bench_sageir_hetero(
                        dataset=dataset,
                        model=sageir_model,
                        d_hidden=d_hidden,
                    )
                    time.sleep(2.0)
                    return


def main():
    benchmark = Benchmark()
    # benchmark.dataset_info()
    # benchmark.bench_homogenous()
    benchmark.bench_heterogenous()
    # dataset = pygds.Entities(root='.data', name='AIFB', hetero=True)
    # benchmark._bench_pyg_hetero(dataset, PyGRGATModel, 8)
    a = 0


if __name__ == "__main__":
    main()
