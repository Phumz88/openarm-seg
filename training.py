import numpy as np
import tensorflow as tf
import os
import sys
sys.path.append('src/')
import nn
from math import floor, ceil
import pipeline
import Unet
import logging
import argparse
import configparser
import pickle
from shutil import copyfile
os.environ["CUDA_VISIBLE_DEVICES"]="0"


logger = logging.getLogger('__name__')
stream = logging.StreamHandler(stream=sys.stdout)
stream.setFormatter(logging.Formatter("%(levelname)-8s %(message)s"))
logger.handlers = []
logger.addHandler(stream)
logger.setLevel(logging.INFO)

fh = logging.FileHandler('training_log.log')
fh.setLevel(logging.DEBUG)
logger.addHandler(fh)

logging.getLogger('PIL').setLevel(logging.ERROR)
logging.getLogger('PIL.Image').setLevel(logging.ERROR)
logging.getLogger('tensorflow').setLevel(logging.ERROR)

def main():
    args = get_args()

    if not os.path.isfile('trainingconfig.ini'):
        logger.info("No config file found, setting defaults.")
        configure_defaults()
        logger.info("Rerun file to train a model.")
        sys.exit()

    training_params = get_all_params(args.session_config)

    if args.debug:
        logger.setLevel(level=logging.DEBUG)

    losses, accs, test_acc = train_model(training_params['models_dir'],
                                         training_params['training_data_dir'],
                                         int(training_params['epochs']),
                                         int(training_params['batch_size']),
                                         int(training_params['ckpt_n_epochs']),
                                         int(training_params['max_to_keep']),
                                         int(training_params['ckpt_n_hours']),
                                         args.model_name,
                                         int(training_params['train_percent']),
                                         int(training_params['val_percent']),
                                         int(training_params['test_percent']),
                                         int(training_params['keep_percent']),
                                         int(training_params['mean']),
                                         float(training_params['weight_decay']),
                                         float(training_params['learning_rate']),
                                         float(training_params['dropout']))

    logger.info("Saving training history and info.")

    save_training_hist(losses, accs, test_acc, training_params['models_dir'], args.model_name, args.session_config)


def configure_default_dirs(default_models_dir, default_training_data_dir):
    config = configparser.ConfigParser()
    if os.path.isfile('trainingconfig.ini'):
        config.read('trainingconfig.ini')

    if default_models_dir:
        config['DEFAULT']['models_dir'] = default_models_dir
    elif 'models_dir' not in config['DEFAULT']:
        config['DEFAULT']['models_dir'] = '/models_dir'
    logger.info("Default models_dir is now %s.", config['DEFAULT']['models_dir'])

    if default_training_data_dir:
        config['DEFAULT']['training_data_dir'] = default_training_data_dir
    elif 'training_data_dir' not in config['DEFAULT']:
        config['DEFAULT']['training_data_dir'] = '/training_data_dir'
    logger.info("Default training_data_dir is now %s.", config['DEFAULT']['training_data_dir'])

    with open('trainingconfig.ini', 'w') as configfile:
        config.write(configfile)

def configure_defaults():
    config = configparser.ConfigParser()
    config['DEFAULT']['models_dir'] = '/models_dir'
    config['DEFAULT']['training_data_dir'] = '/training_data_dir'
    config['DEFAULT']['epochs'] = '50'
    config['DEFAULT']['batch_size'] = '1'
    config['DEFAULT']['train_percent'] = '60'
    config['DEFAULT']['val_percent'] = '10' 
    config['DEFAULT']['test_percent'] = '30'
    config['DEFAULT']['mean'] = '0'
    config['DEFAULT']['weight_decay'] = '1e-6'
    config['DEFAULT']['learning_rate'] = '1e-4'
    config['DEFAULT']['dropout'] = '0.5'
    config['DEFAULT']['max_to_keep'] = '1'
    config['DEFAULT']['ckpt_n_hours'] = '1'
    config['DEFAULT']['ckpt_n_epochs'] = '5'
    config['DEFAULT']['keep_percent'] = '100'

    with open('trainingconfig.ini', 'w') as configfile:
        config.write(configfile)

    for key in config['DEFAULT']:
        logger.info("Set value %s to: %s", key, config['DEFAULT'][key])

def get_parameter(param):
    config = configparser.ConfigParser()
    config.read('trainingconfig.ini')
    return config['DEFAULT'][param]

def get_all_params(section='DEFAULT'):
    config = configparser.ConfigParser()
    config.read('trainingconfig.ini')
    return dict(config.items(section))

def get_args():
    parser = argparse.ArgumentParser(description='Train and save a model.')
    parser.add_argument('model_name', action='store', nargs='?', default=None)
    parser.add_argument('--session-config', '-s', action='store', default='DEFAULT')
    parser.add_argument('--models-dir', '-md', action='store')
    parser.add_argument('--training_data_dir', '-td', action='store')
    parser.add_argument('--default-models-dir', '-dm', action='store')
    parser.add_argument('--default-training_data_dir', '-dt', action='store')
    parser.add_argument('--debug', '-de', action='store_true')
    parser.add_argument('--epochs', '-e', action='store', type=int, default=50)

    args = parser.parse_args()

    if not args.model_name:
        if os.path.isfile('trainingconfig.ini'):
            parser.error("model_name is required when training a model.")

    return args

def save_training_hist(losses, val_accs, test_acc, models_dir, model_name, session_config):
    loss_list_name = model_name + "_losses"
    val_accs_name = model_name + "_val_accs"
    test_acc_name = model_name + "_test_acc"
    loss_list_path = os.path.join(os.path.join(models_dir, model_name), loss_list_name)
    val_accs_path = os.path.join(os.path.join(models_dir, model_name), val_accs_name)
    test_acc_path = os.path.join(os.path.join(models_dir, model_name), test_acc_name)

    try:     
        with open(loss_list_path + ".pickle", "wb") as fp:
            pickle.dump(losses, fp)

        with open(val_accs_path + ".pickle", "wb") as fp:
            pickle.dump(val_accs, fp)

        with open(test_acc_path + ".pickle", "wb") as fp:
            pickle.dump(test_acc, fp)
    except:
        logger.debug("Error pickling")


    with open(loss_list_path, 'w') as f:
        for item in losses:
            f.write("%s\n" % item)

    with open(val_accs_path, 'w') as f:
        for item in val_accs:
            f.write("%s\n" % item)

    with open(test_acc_path, 'w') as f:
        for item in test_acc:
            f.write("%s\n" % item)

    orig_config = './trainingconfig.ini'
    config_name = model_name + "_config_" + str(session_config) + ".ini"
    new_config = os.path.join(os.path.join(models_dir, model_name), config_name)
    copyfile(orig_config, new_config)

    new_training_log_path = os.path.join(os.path.join(models_dir, model_name), 'training_log.log')

    copyfile('./training_log.log', new_training_log_path)
    os.remove('./training_log.log')

def train_model(models_dir,
                training_data_dir,
                num_epochs,
                batch_size,
                auto_save_interval,
                max_to_keep,
                ckpt_n_hours,
                model_name,
                train_percent,
                val_percent,
                test_percent,
                keep_percent,
                mean,
                weight_decay,
                learning_rate,
                dropout):

    logger.info("Fetching data.")

    # NOTE: There is a potential bug here where the sizes of augmented/nonaugmented data do not match, i.e. one group is  > 512 and one is < 512. This case is (probably) not handled properly. 

    raw_data_lst_nonaug, seg_data_lst_nonaug, orig_dims = pipeline.load_all_data(training_data_dir, no_empty=True, reorient=True, predicting=False, include_lower=False, load_augmented=False)

    raw_data_lst_aug, seg_data_lst_aug, aug_dims = pipeline.load_all_data(training_data_dir, no_empty=True, reorient=True, predicting=False, include_lower=False, load_augmented=True)



    training_height, training_width = raw_data_lst_nonaug[0].shape[0], raw_data_lst_nonaug[0].shape[1]

    print("type(seg_data_lst_nonaug):", type(seg_data_lst_nonaug))
    print("type(seg_data_lst_nonaug[0]):", type(seg_data_lst_nonaug[0]))

    print("len(raw_data_lst_nonaug), len(seg_data_lst_nonaug): ", len(raw_data_lst_nonaug), len(seg_data_lst_nonaug))

    print("training_height, training_width: ", training_height, training_width)

    print("raw_data_lst_nonaug[0].shape: ", raw_data_lst_nonaug[0].shape)
    print("seg_data_lst_nonaug[0].shape: ", seg_data_lst_nonaug[0].shape)



    logger.debug("ORIG DIMS: %s", orig_dims)

    logger.info("Initializing model.")

    tf.reset_default_graph()
    sess = tf.Session()
    model = Unet.Unet(mean, weight_decay, learning_rate, dropout, h=training_height, w=training_width)
    sess.run(tf.global_variables_initializer())
    saver = tf.train.Saver(max_to_keep=max_to_keep, keep_checkpoint_every_n_hours=ckpt_n_hours)

    x_train, x_val, x_test, y_train, y_val, y_test = pipeline.split_data(raw_data_lst_nonaug,
                                                                         seg_data_lst_nonaug,
                                                                         train_percent,
                                                                         val_percent,
                                                                         test_percent,
                                                                         keep_percent,
                                                                         total_keep = 500)


    if len(raw_data_lst_aug) > 0:
        logger.debug("Splitting augmented data.")
        x_train_aug, x_val_aug, x_test_aug, y_train_aug, y_val_aug, y_test_aug = pipeline.split_data(raw_data_lst_aug,
                                                                                                     seg_data_lst_aug,
                                                                                                     percent_train = 90,
                                                                                                     percent_val = 5,
                                                                                                     percent_test = 5,
                                                                                                     percent_keep = 100,
                                                                                                     total_keep = 1000)

        logger.debug("Extending training set.")

        x_train = np.concatenate((x_train, x_train_aug))
        y_train = np.concatenate((y_train, y_train_aug))

        logger.debug("Generated random indices.")

        indices = np.arange(x_train.shape[0])
        np.random.shuffle(indices)

        logger.debug("Shuffling training set.")

        x_train = x_train[indices]
        y_train = y_train[indices]



    logger.info("Training model. Details:")
    logger.info(" * Model name: %s", model_name)
    logger.info(" * Epochs: %d", num_epochs)
    logger.info(" * Batch size: %d", batch_size)
    logger.info(" * Max checkpoints to keep: %d", max_to_keep)
    logger.info(" * Keeping checkpoint every n hours: %d", ckpt_n_hours)
    logger.info(" * Keeping checkpoint every n epochs: %d", auto_save_interval)
    logger.info(" * Model directory save destination: %s", models_dir)
    logger.info(" * Training data directory: %s", training_data_dir)

    try:
        losses, accs = nn.train(sess,
                                model,
                                saver,
                                x_train,
                                y_train,
                                x_val,
                                y_val,
                                num_epochs,
                                batch_size,
                                auto_save_interval,
                                models_dir = models_dir,
                                model_name = model_name)
    except KeyboardInterrupt:
        logger.info("Training interrupted.")

    logger.info("Training done. Saving model.")

    pipeline.save_model(models_dir, model_name, saver, sess)

    logger.info("Computing accuracy on test set.")

    test_acc = nn.validate(sess, model, x_test, y_test, verbose=True)

    logger.info("Test accuracy: %s", test_acc)

    return losses, accs, test_acc

if __name__ == '__main__':
    main()

