#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Author: zcy
# @Date:   2019-02-11 11:53:24
# @Last Modified by:   zcy
# @Last Modified time: 2019-02-13 10:11:28
import os
import json
import argparse
import torch
from collections import Iterable

import data_loader.data_loaders as module_data
import models.loss as module_loss
import models.metric as module_metric
import models as model_zoo
from utils import Logger, get_instance
from trainer import Trainer
from base import BaseModel

__all__ = ['classifier']

class classifier(BaseModel):
    """ 可以训练 """

    def __init__(self, model='xception', n_classes=10, img_size=(224, 224), data_dir = None,
                    pretrained=False, pretrained_path="./pretrained/", default_init=True):
        """ 初始化时只初始化model model可以是string 也可以是自己创建的model """
        super(classifier, self).__init__()

        self.resume = None
        self.data_loader = None
        self.valid_data_loader = None
        self.train_logger = Logger()
        arch = {
                "type": model, 
                "args": {"n_class": n_classes, "img_size": img_size, 
                "pretrained": pretrained, "pretrained_path": pretrained_path} 
                }
        self.config = {"name": model, "arch": arch, "n_gpu":1}

        if isinstance(model, str):
            self.model = get_instance(model_zoo, 'arch', self.config)
            # self.model = getattr(model_zoo, model)(n_classes, img_size, pretrained, pretrained_path)
        elif callable(model):
            self.model = model
        else:
            self.logger.info("input type is invalid, please set model as str or a callable object")
            raise Exception("model: wrong input error")

        if default_init:
            # self.loss = torch.nn.CrossEntropyLoss() #效果一样
            self.config["loss"] = "cls_loss"
            self.loss = getattr(module_loss, self.config["loss"])
            
            self.config["metrics"] = ["accuracy", "topK_accuracy"]
            self.metrics = [getattr(module_metric, met) for met in self.config['metrics']]

            # build optimizer
            self.config["optimizer"] = {"type": "Adam", "args":{"lr": 0.0003, "weight_decay": 0.00003}}
            optimizer_params = filter(lambda p: p.requires_grad, self.model.parameters())
            self.optimizer = get_instance(torch.optim, 'optimizer', self.config, optimizer_params)

            self.config["lr_scheduler"] = {"type": "StepLR", "args": {"step_size": 50, "gamma": 0.2 }}
            self.lr_scheduler = get_instance(torch.optim.lr_scheduler, 'lr_scheduler', 
                self.config, self.optimizer)

            self.set_trainer()

        if data_dir:
            self.autoset_dataloader(data_dir, batch_size=64, shuffle=True, validation_split=0.2, 
                num_workers=4, transform = None)

    def init_from_config(config_file, resume=None):
        
        config = json.load(open(config_file))

        # setup data_loader instances
        # setup data_loader instances
        data_cng = config['data_loader']['args']
        transform = None if 'transform' not in data_cng else data_cng['transform']
        if not transform and config["arch"]["args"]["img_size"]:
            config['data_loader']['args']['transform'] = config["arch"]["args"]["img_size"]

        data_loader = get_instance(module_data, 'data_loader', config)
        valid_data_loader = data_loader.split_validation()
        loss = getattr(module_loss, config['loss'])
        metrics = [getattr(module_metric, met) for met in config['metrics']]

        model_config = config['arch']['args']
        clf = classifier(config['arch']['type'], model_config['n_class'], model_config['img_size'], 
                    model_config['pretrained'], model_config['pretrained_path'], False)

        optimizer_params = filter(lambda p: p.requires_grad, clf.model.parameters())
        optimizer = get_instance(torch.optim, 'optimizer', config, optimizer_params)
        lr_scheduler = get_instance(torch.optim.lr_scheduler, 'lr_scheduler', config, optimizer)

        # set classifier according to those
        clf.config = config
        clf.set_loss(loss)
        clf.set_metrics(metrics)
        clf.set_optimizer(optimizer)
        clf.set_lr_scheduler(lr_scheduler)
        clf.set_dataloader(data_loader, valid_data_loader)
        clf.set_resume(resume)

        true_classes = len(clf.data_loader.classes)
        model_output = clf.config['arch']['args']['n_class']
        assert true_classes==model_output, "model分类数为{}，可是实际上有{}个类".format(
            model_output, true_classes) 
        
        return clf

    def train(self):
        assert callable(self.model), "model is not callable!!"
        assert callable(self.loss), "loss is not callable!!"
        assert all(callable(met) for met in self.metrics), "metrics is not callable!!"
        assert "trainer" in self.config, "trainer hasn't been configured!!"
        assert isinstance(self.data_loader, Iterable), "data_loader is not iterable!!"

        if "name" not in self.config:
            self.config["name"] = "_".join(self.config["arch"]["type"], 
                self.config["data_loader"]["type"])
        self.trainer = Trainer(self.model, self.loss, self.metrics, self.optimizer, 
            resume=self.resume, config=self.config, data_loader=self.data_loader,
            valid_data_loader=self.valid_data_loader,
            lr_scheduler=self.lr_scheduler,
            train_logger=self.train_logger)        
        self.trainer.train()

    def train_from(self, resume):
        self.set_resume(resume)
        self.train()

    def set_resume(self, resume):
        self.resume = resume
    def set_loss(self, loss):
        self.loss = loss
    def set_metrics(self, metrics):
        self.metrics = metrics
    def set_model(self, model):
        self.model = model

    def set_optimizer(self, optimizer):
        self.config["optimizer"] = {"type": optimizer.__class__.__name__}
        self.optimizer = optimizer

    def set_lr_scheduler(self, lr_scheduler):
        self.lr_scheduler = lr_scheduler

    def set_dataloader(self, data_loader, valid_data_loader):
        self.data_loader = data_loader
        self.valid_data_loader = valid_data_loader
        self.config["data_loader"] = {"type":self.data_loader.__class__.__name__}

    def autoset_dataloader(self, folder, batch_size=32, shuffle=True, validation_split=0.2, 
        num_workers=4, transform = None):
        '''automatic generate data-loader from a given folder'''

        assert os.path(folder).exists(), "data folder doesn't exit!!!"

        if not transform and self.config["arch"]["args"]["img_size"]:
            transform = self.config["arch"]["args"]["img_size"]
        self.data_loader = module_data.AutoDataLoader(folder, batch_size, shuffle, validation_split, 
            num_workers, transform)
        self.valid_data_loader = self.data_loader.split_validation()
        self.config["data_loader"] = {"type":self.data_loader.__class__.__name__}

        true_classes = len(self.data_loader.classes)
        model_output = self.config['arch']['args']['n_class']
        assert true_classes==model_output, "model分类数为{}，可是实际上有{}个类".format(
            model_output, true_classes)
        # self.config["data_loader"]["class_to_idx"] = self.data_loader.class_to_idx

    def set_trainer(self, epochs=50, save_dir="saved/", save_period=2, verbosity=2, 
        verbose_per_epoch=100, monitor = "max val_accuracy", early_stop=10, 
        tensorboardX=True, log_dir="saved/runs"):
        self.config["trainer"] = {"epochs":epochs, "save_dir":save_dir, "save_period":save_period,
            "verbosity":verbosity, "verbose_per_epoch":verbose_per_epoch, "monitor":monitor, 
            "early_stop":early_stop, "tensorboardX":tensorboardX, "log_dir":log_dir }


if __name__ == '__main__':
    mode = 2
    if mode==1:
        clf = classifier.init_from_config('config2.json')
        # clf.train()
        clf.train_from(r'/home/DL/ModelFeast/saved/squeezenet/0212_144855/checkpoint_best.pth')
    else:
        clf = classifier(model='xception', n_classes=12, img_size=6, data_dir = "")
        # clf.autoset_dataloader(r"/home/DL/ModelFeast/data/plants", batch_size=16)
        # clf.set_trainer(epochs=50, save_dir="saved/", save_period=1)
        # clf.train()
        clf.train_from(r'/home/DL/ModelFeast/saved/xception/0212_141619/checkpoint_best.pth')