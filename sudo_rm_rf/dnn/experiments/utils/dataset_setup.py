"""!
@brief Infer Dataset Specific parameters and return generators
@author Efthymios Tzinis {etzinis2@illinois.edu}
@copyright University of Illinois at Urbana-Champaign
"""

from __config__ import WHAM_ROOT_PATH, LIBRI2MIX_ROOT_PATH, \
    MUSDBWAV8K_ROOT_PATH, MUSDBWAV_ROOT_PATH, FUSS_ROOT_PATH, WHAMR_ROOT_PATH
import sudo_rm_rf.dnn.dataset_loader.libri2mix as libri2mix
import sudo_rm_rf.dnn.dataset_loader.wham as wham_loader
import sudo_rm_rf.dnn.dataset_loader.whamr as whamr_loader
import sudo_rm_rf.dnn.dataset_loader.fuss as fuss_loader
import sudo_rm_rf.dnn.dataset_loader.musdb_dataset as \
    musdb_loader


def create_loader_for_simple_dataset(dataset_name=None,
                                     separation_task=None,
                                     data_split=None,
                                     sample_rate=None,
                                     min_or_max=None,
                                     zero_pad=None,
                                     timelegth=None,
                                     n_channels=None,
                                     normalize_audio=None,
                                     n_samples=None,
                                     min_num_sources=None,
                                     max_num_sources=None):
    if dataset_name == 'WHAM':
        loader = wham_loader
        root_path = WHAM_ROOT_PATH
        translator = {'train': 'tr', 'test': 'tt', 'val': 'cv'}
        translated_split = translator[data_split]
    elif dataset_name == 'WHAMR':
        loader = whamr_loader
        root_path = WHAMR_ROOT_PATH
        translator = {'train': 'tr', 'test': 'tt', 'val': 'cv'}
        translated_split = translator[data_split]
    elif dataset_name == 'FUSS':
        loader = fuss_loader
        root_path = FUSS_ROOT_PATH
        translator = {'train': 'train', 'test': 'eval', 'val': 'validation'}
        translated_split = translator[data_split]
    elif dataset_name == 'LIBRI2MIX':
        loader = libri2mix
        root_path = LIBRI2MIX_ROOT_PATH
        if n_samples > 13900 and data_split == 'train':
            print('Going to use train-360 for training LibriMix...')
            translated_split = 'train-360'
        elif n_samples <= 13900 and data_split == 'train':
            print('Going to use train-100 for training LibriMix...')
            translated_split = 'train-100'
        elif data_split == 'test':
            translated_split = 'test'
        elif data_split == 'val':
            translated_split = 'dev'
    elif dataset_name == 'MUSDB':
        loader = musdb_loader
        if sample_rate == 8000.:
            root_path = MUSDBWAV8K_ROOT_PATH
        elif sample_rate == 44100.:
            root_path = MUSDBWAV_ROOT_PATH
        else:
            raise ValueError('Not appropriate sampling rate for MUSDB.')
        translated_split = data_split
    else:
        raise ValueError('Dataset: {} is not yet supported!'.format(
            dataset_name))

    data_loader = loader.Dataset(
        root_dirpath=root_path, task=separation_task,
        split=translated_split, sample_rate=sample_rate, timelength=timelegth,
        zero_pad=zero_pad, min_or_max=min_or_max, n_channels=n_channels,
        augment='tr' in data_split,
        normalize_audio=normalize_audio, n_samples=n_samples,
        min_num_sources=min_num_sources, max_num_sources=max_num_sources)
    return data_loader

def setup(hparams):
    # Create all generators
    generators = {}
    for data_split in ['train', 'val', 'test', 'train_val']:
        if hparams[data_split] is None:
            generators[data_split] = None
            continue

        if len(hparams[data_split]) > 1:
            raise ValueError('Current implementation does not support '
                             'training using multiple datasets.')

        loader = create_loader_for_simple_dataset(
                    dataset_name=hparams[data_split][0],
                    separation_task=hparams['separation_task'],
                    data_split=data_split.split('_')[0],
                    sample_rate=hparams['fs'],
                    n_channels=hparams['n_channels'],
                    min_or_max=hparams['min_or_max'],
                    zero_pad=hparams['zero_pad_audio'],
                    timelegth=hparams['audio_timelength'],
                    normalize_audio=hparams['normalize_audio'],
                    n_samples=hparams['n_'+data_split],
                    min_num_sources=hparams['min_num_sources'],
                    max_num_sources=hparams['max_num_sources'])
        generators[data_split] = loader.get_generator(
            batch_size=hparams['batch_size'], num_workers=hparams['n_jobs'])

    return generators