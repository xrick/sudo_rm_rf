"""!
@brief Run an initial CometML experiment with multiple

@author Efthymios Tzinis {etzinis2@illinois.edu}
@copyright University of Illinois at Urbana-Champaign
"""

import os
import sys

sys.path.append('../../../')
from __config__ import API_KEY

from comet_ml import Experiment

import torch
from tqdm import tqdm
from pprint import pprint
import sudo_rm_rf.dnn.experiments.utils.dataset_specific_params \
    as dataset_specific_params
import sudo_rm_rf.dnn.losses.sisdr as sisdr_lib
import sudo_rm_rf.dnn.utils.cometml_loss_report as cometml_report
import sudo_rm_rf.dnn.utils.metrics_logger as metrics_logger
import sudo_rm_rf.dnn.utils.cometml_log_audio as cometml_audio_logger
import sudo_rm_rf.dnn.experiments.utils.cmd_args_parser as parser
import sudo_rm_rf.dnn.models.sudormrf as sudormrf
import sudo_rm_rf.dnn.experiments.utils.hparams_parser as hparams_parser


args = parser.get_args()
hparams = hparams_parser.get_hparams_from_args(args)
dataset_specific_params.update_hparams(hparams)

if hparams["log_audio"]:
    audio_logger = cometml_audio_logger.AudioLogger(
        fs=hparams["fs"], bs=hparams["bs"], n_sources=hparams["n_sources"])

experiment = Experiment(API_KEY, project_name=hparams["project_name"])
experiment.log_parameters(hparams)

experiment_name = '_'.join(hparams['tags'])
for tag in hparams['tags']:
    experiment.add_tag(tag)

if hparams['experiment_name'] is not None:
    experiment.set_name(hparams['experiment_name'])
else:
    experiment.set_name(experiment_name)

# define data loaders
train_gen, val_gen, tr_val_gen = dataset_specific_params.get_data_loaders(hparams)

os.environ['CUDA_VISIBLE_DEVICES'] = ','.join([cad
                                               for cad in hparams['cuda_devs']])

back_loss_tr_loss_name, back_loss_tr_loss = (
    'tr_back_loss_SISDRi',
    sisdr_lib.PermInvariantSISDR(batch_size=hparams['bs'],
                                 n_sources=hparams['n_sources'],
                                 zero_mean=True,
                                 backward_loss=True,
                                 improvement=True))

val_losses = dict([
    ('val_SISDRi', sisdr_lib.PermInvariantSISDR(batch_size=hparams['bs'],
                                                n_sources=hparams['n_sources'],
                                                zero_mean=True,
                                                backward_loss=False,
                                                improvement=True,
                                                return_individual_results=True))
  ])
val_loss_name = 'val_SISDRi'

tr_val_losses = dict([
    ('tr_SISDRi', sisdr_lib.PermInvariantSISDR(batch_size=hparams['bs'],
                                               n_sources=hparams['n_sources'],
                                               zero_mean=True,
                                               backward_loss=False,
                                               improvement=True,
                                               return_individual_results=True))])

model = sudormrf.SuDORMRF(out_channels=hparams['out_channels'],
                          in_channels=hparams['in_channels'],
                          num_blocks=hparams['num_blocks'],
                          upsampling_depth=hparams['upsampling_depth'],
                          enc_kernel_size=hparams['enc_kernel_size'],
                          enc_num_basis=hparams['enc_num_basis'],
                          num_sources=hparams['n_sources'])

numparams = 0
for f in model.parameters():
    if f.requires_grad:
        numparams += f.numel()
experiment.log_parameter('Parameters', numparams)
print('Trainable Parameters: {}'.format(numparams))


model = torch.nn.DataParallel(model).cuda()

opt = torch.optim.Adam(model.parameters(), lr=hparams['learning_rate'])

all_losses = [back_loss_tr_loss_name] + \
             [k for k in sorted(val_losses.keys())] + \
             [k for k in sorted(tr_val_losses.keys())]

tr_step = 0
val_step = 0
for i in range(hparams['n_epochs']):
    res_dic = {}
    for loss_name in all_losses:
        res_dic[loss_name] = {'mean': 0., 'std': 0., 'acc': []}
    print("Experiment: {} - {} || Epoch: {}/{}".format(experiment.get_key(),
                                                       experiment.get_tags(),
                                                       i+1,
                                                       hparams['n_epochs']))
    model.train()

    for data in tqdm(train_gen, desc='Training'):
        opt.zero_grad()
        m1wavs = data[0].unsqueeze(1).cuda()
        clean_wavs = data[-1].cuda()

        rec_sources_wavs = model(m1wavs)

        l = back_loss_tr_loss(rec_sources_wavs,
                              clean_wavs,
                              initial_mixtures=m1wavs)
        l.backward()

        if hparams['clip_grad_norm'] > 0:
            torch.nn.utils.clip_grad_norm_(model.parameters(),
                                           hparams['clip_grad_norm'])
        opt.step()
        res_dic[back_loss_tr_loss_name]['acc'].append(l.item())
    tr_step += 1

    if hparams['reduce_lr_every'] > 0:
        if tr_step % hparams['reduce_lr_every'] == 0:
            new_lr = (hparams['learning_rate']
                      / (hparams['divide_lr_by'] ** (tr_step // hparams['reduce_lr_every'])))
            print('Reducing Learning rate to: {}'.format(new_lr))
            for param_group in opt.param_groups:
                param_group['lr'] = new_lr

    if val_gen is not None:
        model.eval()
        with torch.no_grad():
            for data in tqdm(val_gen, desc='Validation'):
                m1wavs = data[0].unsqueeze(1).cuda()
                clean_wavs = data[-1].cuda()

                rec_sources_wavs = model(m1wavs)
                for loss_name, loss_func in val_losses.items():
                    l = loss_func(rec_sources_wavs,
                                  clean_wavs,
                                  initial_mixtures=m1wavs)
                    res_dic[loss_name]['acc'] += l.tolist()
            if hparams["log_audio"]:
                audio_logger.log_batch(rec_sources_wavs, clean_wavs, m1wavs,
                                       experiment, step=val_step)

    val_step += 1

    if tr_val_losses.values():
        model.eval()
        with torch.no_grad():
            for data in tqdm(tr_val_gen, desc='Train Validation'):
                m1wavs = data[0].unsqueeze(1).cuda()
                clean_wavs = data[-1].cuda()

                rec_sources_wavs = model(m1wavs)
                for loss_name, loss_func in tr_val_losses.items():
                    l = loss_func(rec_sources_wavs,
                                  clean_wavs,
                                  initial_mixtures=m1wavs)
                    res_dic[loss_name]['acc'] += l.tolist()
    if hparams["metrics_log_path"] is not None:
        metrics_logger.log_metrics(res_dic, hparams["metrics_log_path"],
                                   tr_step, val_step,
                                   cometml_experiment=experiment)

    res_dic = cometml_report.report_losses_mean_and_std(res_dic,
                                                        experiment,
                                                        tr_step,
                                                        val_step)

    for loss_name in res_dic:
        res_dic[loss_name]['acc'] = []
    pprint(res_dic)
