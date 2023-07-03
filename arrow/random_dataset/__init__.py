# @Time    : 2022/9/18 10:49
# @Author  : tk
# @FileName: __init__.py.py
import logging
import math
import typing
import os
import warnings
from typing import List
from .. import RandomDatasetBase
import pickle
from ..default import global_default_options

# from collections.abc import Sized
import copy

from tfrecords.python.io.arrow import IPC_StreamReader,IPC_MemoryMappedFileReader,arrow

logging.basicConfig(level=logging.INFO)


__all__ = [
    "SingleArrowRandomDataset",
    "MultiArrowRandomDataset",
    "IPC_StreamReader",
    "IPC_MemoryMappedFileReader",
    "arrow"
]


class SingleArrowRandomDataset(RandomDatasetBase):
    def __init__(self,
                 path: typing.Union[typing.AnyStr,typing.Sized],
                 col_names: typing.Optional[typing.List[str]] = None,
                 options=None,
                 with_share_memory=False
                 ):
        super(SingleArrowRandomDataset, self).__init__()
        default_options = copy.deepcopy(global_default_options)
        if options is not None:
            default_options.update(options)

        self.with_share_memory = with_share_memory

        self.path = path
        self.col_names = col_names
        self.options = options

        self._file_reader = None
        self._table = None
        self.length = 0
        self.reset()

    def __del__(self):
       self.close()

    def reset(self):
        self.repeat_done_num = 0
        self.__reopen__()

    def close(self):
        if hasattr(self, '_file_reader') and self._file_reader:
            self._file_reader.close()
            self._file_reader = None


    def __reopen__(self):
        self.block_id = -1
        self.close()
        if os.path.exists(self.path):
            try:
                if self.with_share_memory:
                    self._file_reader = IPC_MemoryMappedFileReader(self.path,options=self.options)
                    self.length = self._file_reader.count_rows() if self._file_reader is not None else 0
                    batches = []
                    for i in range(self._file_reader.num_record_batches()):
                        batches.append( self._file_reader.read_batch(i))
                    self._table: arrow.Table = arrow.Table.FromRecordBatches(batches).Value()
                else:
                    self._file_reader = IPC_StreamReader(self.path,options=self.options)
                    self._table: arrow.Table = self._file_reader.read_all().Flatten().Value()
                    self.length = self._table.num_rows() if self._table is not None else 0
                self._table = self._table.CombineChunksToBatch(arrow.default_memory_pool()).Value()
                if self.col_names is None:
                    schema : arrow.Schema = self._table.schema()
                    col_names = schema.field_names()
                else:
                    col_names = self.col_names

                self.cols = [self._table.GetColumnByName(n) for n in col_names]
            except Exception as e:
                self._file_reader = None
                self._table = None
                self.cols = None
                warnings.warn(str(e))
        else:
            self._file_reader = None
            self._table = None

        self.repeat_done_num += 1
        return True

    def __len__(self):
        return self.length

    def __getitem__(self, item):
        if self._file_reader is None:
            raise OverflowError

        if isinstance(item, slice):
            return self.__getitem_slice__(item)

        x = ()
        for col in self.cols:
            x += (col.Value(item),)

        return x


class MultiArrowRandomDataset(RandomDatasetBase):
    def __init__(self,
                 data_path_data_list: List[typing.Union[typing.AnyStr,typing.Sized]],
                 col_names: typing.Optional[typing.List[str]] = None,
                 options=None,
                 with_share_memory=False
                 ) -> None:
        super(MultiArrowRandomDataset, self).__init__()

        self.with_share_memory = with_share_memory
        self.options = options
        self.col_names = col_names
        self.data_path_data_list = data_path_data_list
        self.reset()

    def reset(self):
        self.iterators_ = [{"valid": False,"file": self.data_path_data_list[i]} for i in range(len(self.data_path_data_list))]
        self.cicle_iterators_ = []
        self.fresh_iter_ids = False
        self.cur_id = 0
        self.__reopen__()

    def close(self):
        for iter_obj in self.iterators_:
            if iter_obj["valid"] and "instance" in iter_obj and iter_obj["instance"]:
                iter_obj["instance"].close()
                iter_obj["valid"] = False
                iter_obj["instance"] = None

    def __reopen__(self):
        for it_obj in self.iterators_:
            it_obj['inst'] = SingleArrowRandomDataset(it_obj["file"],
                                                      col_names=self.col_names,
                                                      options=self.options,
                                                      with_share_memory=self.with_share_memory)

    def __len__(self):
        total_len = 0
        for it_obj in self.iterators_:
            total_len += len(it_obj['inst'])
        return total_len

    def __getitem__(self, item):
        if isinstance(item, slice):
            return self.__getitem_slice__(item)

        cur_len = 0
        obj = None
        for i,it_obj in enumerate(self.iterators_):
            tmp_obj = it_obj['inst']
            if item < cur_len + len(tmp_obj):
                obj = tmp_obj
                break
            cur_len += len(tmp_obj)
        if obj is None:
            raise OverflowError
        real_index =  item - cur_len
        return obj[real_index]
