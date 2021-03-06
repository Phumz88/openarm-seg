import os
from math import floor, ceil, log
import numpy as np
import tensorflow as tf
import sys
sys.path.append('src/')
import nn
import nibabel as nib
import scipy.sparse
from scipy.misc import imresize
import Unet
import logging
import gc


logger = logging.getLogger('__name__')
logger.setLevel(logging.DEBUG)

##################################
# DATA FUNCTIONS
##################################

def split_data(raw_data, seg_data, percent_train, percent_val, percent_test, percent_keep, total_keep = 0):
    assert len(raw_data) == len(seg_data)
    assert percent_train + percent_val + percent_test == 100

    x_train, y_train = [], []
    x_val, y_val = [], []
    x_test, y_test = [], []

    height, width = raw_data[0].shape

    reduced_range = floor(percent_keep/100*len(raw_data))
    logger.debug(reduced_range)
    num_train = np.round(reduced_range * percent_train/100).astype(np.int)
    num_val = np.round(num_train + reduced_range * percent_val/100).astype(np.int)
    num_test = np.round(num_val + reduced_range * percent_test/100).astype(np.int)

    rand_indices = list(np.random.choice(floor((percent_keep/100)*len(raw_data)), floor((percent_keep/100)*len(raw_data)), replace=False))

    
    logger.debug("Randomizing data sets (in split_data).")

    for i in rand_indices[:num_train]:
        x_train.append(raw_data[i])
        y_train.append(seg_data[i])
    for j in rand_indices[num_train:num_val]:
        x_val.append(raw_data[j])
        y_val.append(seg_data[j])
    for k in rand_indices[num_val:num_test]:
        x_test.append(raw_data[k])
        y_test.append(seg_data[k])

    x_train = np.array(x_train).reshape((len(x_train), height, width, 1))
    x_val = np.array(x_val).reshape((len(x_val), height, width, 1))
    x_test = np.array(x_test).reshape((len(x_test), height, width, 1))
    y_train = np.array(y_train)
    y_val = np.array(y_val)
    y_test = np.array(y_test)

    if total_keep != 0:
        x_train = x_train[:total_keep]
        y_train = y_train[:total_keep]


    logger.debug(x_train.shape)
    logger.debug(x_test.shape)
    logger.debug(x_val.shape)
    logger.debug(y_train.shape)
    logger.debug(y_test.shape)
    logger.debug(y_val.shape)

    return x_train, x_val, x_test, y_train, y_val, y_test

def one_hot_encode(L, class_labels):
    """
    TODO: ensure encoding remains consistent

    2D array (image) of segmentation labels -> .npy
    # One Hot Encode the label 2d array -> .npy files with dim (h, w, len(class_labels))
    # num classes will be 8? but currently dynamically allocated based on num colors in all scans.
    """
    print("L shape:", L.shape)
    h, w = L.shape
    try:
        encoded = np.array([list(map(class_labels.index, L.flatten()))])

        L = encoded.reshape(h, w)

        Lhot = np.zeros((L.shape[0], L.shape[1], len(class_labels)))
        for i in range(L.shape[0]):
            for j in range(L.shape[1]):
                Lhot[i,j,L[i,j]] = 1
        return Lhot
    except Exception as e:
        print("Error during one hot encoding:", e)

def save_one_hot_encoded(nii_data_arr, class_labels, save_local=False, save_name=None, save_dir=None):
    """
    Takes a NIfTI file in Numpy array form and returns a one-hot-encoded version of the array. Optionally has the
    side-effect of saving a copy of the encoded array to memory.

    Args:
        nii_data_arr (numpy.ndarray): Numpy array of shape (N, height, width) corresponding to a NIfTI file, where
            the first dimension is interpreted as the number of contained cross-sections, each one of shape
            (height, width).
        class_labels (list): List of ints corresponding to the class labels of a scan.
        save_local (boolean): Boolean flag indicating whether or not to save a copy of the resulting numpy array
            to local storage.
        save_name (str): Filename to save the resulting numpy array with (excluding file extension) if save_local
            is set to True.
        save_dir (str): Path to save destination of resulting numpy array if save_local is set to True.

    Returns:
        numpy.ndarray: Numpy array of shape (N, height, width, len(class_labels)). A one-hot-encoded version of
            nii_data_arr according to class_labels.
    """
    encoded_nii_data_arr = np.empty((nii_data_arr[0], nii_data_arr[1], nii_data_arr[2], len(class_labels)))
    for i in range(nii_data_arr.shape[0]):
        logger.debug(i)
        encoded_img = one_hot_encode(nii_data_arr[i], class_labels)
        encoded_nii_data_arr[i] = encoded_img
    if save_local and save_name and save_dir:
        save_sparse_csr(os.path.join(save_dir, save_name), encoded_nii_data_arr)
    return encoded_nii_data_arr


def convert_label_vals(seg):
    """
    Converts the intensity values of a predicted segmentation to the label values of the original segmentations.
    That is, it converts label values in [0, 1, 2, 3, 4, 5, 6, 7, 8] to [0, 7, 8, 9, 45, 51, 52, 53, 68]. This is 
    done so that predicted segmentations can be directly compared with ground truth.

    Args:
        seg (numpy.ndarray): Numpy array of shape (height, width). Usually (512, 512).

    Returns:
        numpy.ndarray: Numpy array of shape (height, width), the same as the input, where the label values have
            been changed to match ground truth segmentation convention.
    """
    orig_label_vals = [0, 7, 8, 9, 45, 51, 52, 53, 68]
    converted = [orig_label_vals[i] for i in seg.flatten()]
    converted_arr = np.array(converted)
    converted_arr = converted_arr.reshape(seg.shape)
    return converted_arr

def show_images(images, cols = 1, titles = None):
    """Display a list of images in a single figure with matplotlib.
    
    Parameters
    ---------
    images: List of np.arrays compatible with plt.imshow.
    
    cols (Default = 1): Number of columns in figure (number of rows is 
                        set to np.ceil(n_images/float(cols))).
    
    titles: List of titles corresponding to each image. Must have
            the same length as titles.
    """
    assert((titles is None) or (len(images) == len(titles)))
    n_images = len(images)
    if titles is None: titles = ['Image (%d)' % i for i in range(1,n_images + 1)]
    fig = plt.figure()
    for n, (image, title) in enumerate(zip(images, titles)):
        a = fig.add_subplot(cols, np.ceil(n_images/float(cols)), n + 1)
#         if image.ndim == 2:
#             plt.gray()
        plt.imshow(image)
        a.set_title(title)
    fig.set_size_inches(np.array(fig.get_size_inches()) * n_images)
    plt.show()

def save_sparse_csr(filename, array):
    # note that .npz extension is added automatically
    np.savez(filename, data=array.data, indices=array.indices,
             indptr=array.indptr, shape=array.shape)
    
def load_sparse_csr(filename):
    # Sparse matrix reading function to read our raw .npz files
    assert filename.endswith('.npz')
    loader = np.load(filename)  # filename must end with .npz
    return scipy.sparse.csr_matrix((loader['data'], loader['indices'], loader['indptr']),
                      shape=loader['shape'])

def load_compressed_npz(filename):
    data = np.load(filename)
    return data['arr_0']


def get_raw_pixel_classes(trial_name, raw_nifti_dir):
    trial_segmentation = None
    
    for raw_nii in os.listdir(raw_nii_dir):
        if raw_nii.startswith(trial_name) and raw_nii.endswith(".nii"):
            if "seg" in raw_nii:
                trial_segmentation = os.path.join(raw_nii_dir, raw_nii)
                break
    
    scan_voxel = nib.load(trial_segmentation)
    struct_arr = scan_voxel.get_data()
    class_labels = sorted(list(np.unique(struct_arr)))
    return class_labels
    
def check_one_hot(encoded_img):
    logger.debug(encoded_img.shape)
    return np.all(np.sum(encoded_img, axis=2) == 1.)

def batch_img_resize(images, h = 256, w = 256):
    images_resized = np.zeros([0, newHeight, newWidth], dtype=np.uint8)
    for image in range(images.shape[0]):
        temp = imresize(images[image], [h, w], 'nearest')
        images_resized = np.append(images_resized, np.expand_dims(temp, axis=0), axis=0)
    return images_resized

def crop_image(img, height, width):
    orig_height, orig_width = img.shape
    height_remove = (orig_height - height) / 2
    width_remove = (orig_width - width) / 2
    ht_idx_1 = floor(height_remove)
    ht_idx_2 = ceil(height_remove)
    wd_idx_1 = floor(width_remove)
    wd_idx_2 = ceil(width_remove)
    
    cropped = img[ht_idx_1:orig_height-ht_idx_2, wd_idx_1:orig_width-wd_idx_2]
    
    return cropped

def pad_image(orig_img, height, width):    
    orig_height, orig_width = orig_img.shape
    
    height_pad = (height - orig_height) / 2
    width_pad = (width - orig_width) / 2
    print("new height:", height, "orig height:", orig_height)
    print("new width:", width, "orig width", orig_width)
    print("height_pad:", height_pad, "width_pad:", width_pad)
    
    height_top_pad = floor(height_pad)
    height_bot_pad =  ceil(height_pad)
    width_left_pad = floor(width_pad)
    width_right_pad = ceil(width_pad)
    
    pad_dims = ((height_top_pad, height_bot_pad), (width_left_pad, width_right_pad))
    padded_img = np.pad(orig_img, pad_width=pad_dims, mode='constant', constant_values=0)
    

    return padded_img


def find_training_dim(scan_paths):
    # ASSUMPTION: the 'actual' max dimension always corresponds to the number of cross sections, so ignore that one.
    # This is actually the second largest in the dims of the niftis (we want the largest dimension not along the arm)
    max_dim = 0
    for scan_path in scan_paths:
        print("curr scan_path:", scan_path)
        for item in os.listdir(scan_path):
            # Assume any non hidden file in the scan path is a nifti we're looking for. Set directories so this is true.
            item_path = os.path.join(scan_path, item)
            print(item_path)
            if os.path.isfile(item_path) and not item.startswith('.'):
                nifti = nib.load(item_path)
                nifti_shape = nifti.get_fdata().shape
                curr_max = sorted(nifti_shape, reverse=True)[1] # Second largest
                if curr_max > max_dim:
                    max_dim = curr_max
    gc.collect()
    print("the max dim is: ", max_dim)

    # return 512 if max_dim <= 512 else 1024
    return max_dim

def load_all_data(training_dir, encode_segs=False, use_pre_encoded=True, no_empty=False, reorient=True, predicting=False, include_lower=True, load_augmented=False):
    raw_images = []
    segmentations = []    
    scan_paths = []
    
    print(os.listdir(training_dir))
    for folder in os.listdir(training_dir):
        if os.path.isdir(os.path.join(training_dir, folder)) and not folder.startswith('.') and 'trial' in folder.lower():
            if folder.lower().endswith("_ed") or folder.lower().endswith("_rot"):
                if load_augmented:
                    scan_folder_path = os.path.join(training_dir, folder)
                    scan_paths.append(scan_folder_path)
                else:
                    continue
            else:
                if not load_augmented:
                    scan_folder_path = os.path.join(training_dir, folder)
                    scan_paths.append(scan_folder_path)
                else:
                    continue

    
    logger.debug("%s", scan_paths)

    if len(scan_paths) == 0:
        return [], [], None

    max_dim = find_training_dim(scan_paths)

    training_dim = 512 if max_dim <= 512 else 1024
    
    for scan_path in scan_paths:
        scan_data_raw, scan_data_labels, orig_dims = load_data(scan_path, reorient, training_dim, training_dim, encode_segs, use_pre_encoded, no_empty, predicting, include_lower)
        raw_images.extend(scan_data_raw)
        segmentations.extend(scan_data_labels)
    
    return raw_images, segmentations, orig_dims


def load_data(nifti_training_dir, reorient, height, width, encode_segs=False, use_pre_encoded=True, no_empty=False, predicting=False, include_lower=True):
    # Label casting is done to attempt to fix mislabeling of one class. 
    label_cast_source = 1
    label_cast_dest = 7
    default_raw_pixel_classes = [0, 7, 8, 9, 45, 51, 52, 53, 68]

    raw_images = []
    segmentations = []    
    scan_files = []
    
    logger.debug("====")
    logger.debug(nifti_training_dir)
    logger.debug("====")
    
    raw_nifti_arr = None
    if predicting:
        seg_nifti_arr = np.empty((1,1,1))
    else:
        seg_nifti_arr = None

    for item in os.listdir(nifti_training_dir):
        item_path = os.path.join(nifti_training_dir, item)
        if os.path.isfile(item_path) and not item.startswith('.'):
            if 'vol' in item:
                raw_nifti_arr = load_nifti_data(item_path)
            elif 'seg' in item and not predicting:
                seg_nifti_arr = load_nifti_data(item_path)
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            
    # raw_nifti_arr = np.rint(raw_nifti_arr).astype(int)
    seg_nifti_arr = np.rint(seg_nifti_arr).astype(int)
    # correct label anomaly
    seg_nifti_arr[seg_nifti_arr == 6] = 7

    orig_dims = raw_nifti_arr.shape
    # ASSUMPTION: Apply same transformation to all niftis to get proper orientation, that is, swap (x, y) dimensions. This is to match the orientation of our new data
    # to previous data. Reorienting is not required in general.
    if reorient:
        print("reorienting")
        print("before dims:", raw_nifti_arr.shape, seg_nifti_arr.shape)
        raw_nifti_arr = np.swapaxes(raw_nifti_arr, 0, 2)
        seg_nifti_arr = np.swapaxes(seg_nifti_arr, 0, 2)
        print("new dims:", raw_nifti_arr.shape, seg_nifti_arr.shape)

    if not include_lower:
        raw_nifti_arr = raw_nifti_arr[raw_nifti_arr.shape[0]-650:]
        seg_nifti_arr = seg_nifti_arr[seg_nifti_arr.shape[0]-650:]

    for i in range(raw_nifti_arr.shape[0]):
        if (no_empty and np.all(raw_nifti_arr[i] == 0)):
            logger.debug("Slice skipped due to being empty: %s", i)
            continue

        print("Padding and encoding from", nifti_training_dir, ":", i)
        raw_images.append(pad_image(raw_nifti_arr[i], height, width))

        if not predicting:
            print("ADDED SEG")
            padded_image = pad_image(seg_nifti_arr[i], height, width)
            casted_image = cast_label_numbers(padded_image, label_cast_source, label_cast_dest)
            encoded_seg = one_hot_encode(casted_image, default_raw_pixel_classes)
            print("ENCODED SEG SHAPE:", encoded_seg.shape)
            segmentations.append(encoded_seg)

        
    return raw_images, segmentations, orig_dims


def cast_label_numbers(seg_image_slice, src, dst):
    np.place(seg_image_slice, seg_image_slice == src, dst)
    return seg_image_slice
    


def load_nifti_data(nifti_path):
    nifti = nib.load(nifti_path)
    return nifti.get_fdata()

def save_arr_as_nifti(arr, orig_nifti_name, save_name, nii_data_dir, save_dir):
    '''
    orig_nifti_name should include file extension .nii.
    '''

    original_vol_path = os.path.join(nii_data_dir, orig_nifti_name)
    original_vol = nib.load(original_vol_path)
    new_header = original_vol.header.copy()
    new_nifti = nib.nifti1.Nifti1Image(arr, None, header=new_header)
    if not (os.path.exists(save_dir) and os.path.isdir(save_dir)):
        os.mkdir(save_dir)
    save_path = os.path.join(save_dir, save_name)

    nib.save(new_nifti, save_path)

def get_orig_nifti_name(trial_name, nii_data_dir, identifier):
    for file_name in os.listdir(nii_data_dir):
        if trial_name in file_name:
            file_path = os.path.join(nii_data_dir, file_name)
            if identifier in file_name and os.path.isfile(file_path):
                logger.debug("Found .nii at %s", file_path)
                return file_name
    return None

def check_nifti_equal(first_nii, second_nii, nii_data_dir):
    """
    Args:
        first_nii (str): Filename of first .nii file, including extension.
        second_nii (str): Filename of second .nii file, including extension.
        nii_data_dir (str): Path to directory containing first_nii and second_nii.

    Returns:
        boolean: Returns true if all voxel values of first_nii and second_nii are equal. The dimensions of the scans
            must be the same in order to be considered equal.
    """
    first_nii_path = os.path.join(nii_data_dir, first_nii)
    second_nii_path = os.path.join(nii_data_dir, second_nii)
    first_nii_full = nib.load(first_nii_path)
    second_nii_full = nib.load(second_nii_path)
    first_nii_data = first_nii_full.get_fdata()
    second_nii_data = second_nii_full.get_fdata()
    return np.array_equal(first_nii_data, second_nii_data)

def reorient_nifti_arr(nifti_arr):
    return np.swapaxes(nifti_arr, 0, 2)


##################################
# PREDICTION FUNCTIONS
##################################

def predict_image(img, model, sess):
    prediction = model.predict(sess, img)
    pred_classes = np.argmax(prediction[0], axis=2)
    return pred_classes

def predict_whole_seg(img_arr, model, sess, crop=False, orig_dims=None, predict_lower=True):
    if len(img_arr.shape) == 3:
        img_arr = np.expand_dims(img_arr, axis=3)
    segmented = np.empty(img_arr.shape[:3])

    logger.debug("imr_arr shape: %s", img_arr.shape)
    logger.debug("segmented arr shape: %s", segmented.shape)
    num_sections = img_arr.shape[0]

    lower_bound = (img_arr.shape[0] - 650) if not predict_lower else 0

    blank_slice = np.zeros(segmented[0].shape)

    logger.debug("blank slice shape: %s", blank_slice.shape)

    for i in range(num_sections):
        logger.debug("%s", i)

        if i > lower_bound:
            pred = predict_image(img_arr[i:i+1], model, sess)
            pred = convert_label_vals(pred)
        else:
            pred = blank_slice
        # print("unique vals before convert: ", np.unique(pred))
        # print("unique vals after convert: ", np.unique(pred))
        if crop and orig_dims:
            segmented[i] = crop_image(pred, orig_dims[0], orig_dims[1])
        else:
            segmented[i] = pred
    return segmented


def predict_all_segs(to_segment_dir, save_dir, nii_data_dir, model, sess, reorient, predict_lower=True):
    """
    Produce segmentations of arbitrary number of preprocessed scans and save them all as Nifti
    files. Each preprocessed scan should be in separate subfolder. Names of folders containing 
    scan data should start with "trial".
    """
    scan_paths = []
    trials = []
    
    for folder in os.listdir(to_segment_dir):
        logger.debug(folder)
        if os.path.isdir(os.path.join(to_segment_dir, folder)) and folder.startswith('trial'):
            scan_path = os.path.join(to_segment_dir, folder)
            scan_paths.append(scan_path)
            trials.append(folder)
    
    logger.debug("")
    logger.debug("trials found: %s", trials)
    logger.debug("====")

    for i in range(len(scan_paths)):

        scan_path = scan_paths[i]
        trial_name = trials[i]

        orig_nifti_name = get_orig_nifti_name(trial_name, nii_data_dir, 'volume')
        logger.debug("orig_nifti: %s", orig_nifti_name)

        logger.debug("trial_name = %s", trial_name)

        if os.path.isfile(os.path.join(save_dir, trial_name + "_pred_seg.nii")):
            logger.debug("skipped %s due to preexisting prediction", trial_name)
            continue

        max_dim = find_training_dim([scan_path])
        training_dim = 512 if max_dim <= 512 else 1024

        raw_scan_data, ignore, orig_dims = load_data(scan_path, reorient, training_dim, training_dim, encode_segs=False, predicting=True, no_empty=False)
        logger.debug("%s: %d", scan_path, len(raw_scan_data))
        raw_scan_data_arr = np.asarray(raw_scan_data)
        logger.debug("Predicting segmentation for %s", trial_name)
        pred_seg = predict_whole_seg(raw_scan_data_arr, model, sess, predict_lower=predict_lower)

        print("orig dims:", orig_dims)
        print("pred_seg dims:", pred_seg.shape)
        restore_height, restore_width = orig_dims[1], orig_dims[2]
        if reorient:
            restore_height, restore_width = orig_dims[1], orig_dims[0]

        cropped_pred_seg = np.empty((pred_seg.shape[0], restore_height, restore_width))

        for i in range(pred_seg.shape[0]):
            cropped_pred_seg[i] = crop_image(pred_seg[i], restore_height, restore_width)

        print("cropped_pred_seg dims:", cropped_pred_seg.shape)
        if reorient:
            cropped_pred_seg = reorient_nifti_arr(cropped_pred_seg)
            print("reoriented cropped_pred_seg dims:", cropped_pred_seg.shape)
        
        pred_seg = cropped_pred_seg

        pred_seg = np.rint(pred_seg)

        save_name = trial_name + '_pred_seg.nii'

        save_arr_as_nifti(pred_seg, orig_nifti_name, save_name, nii_data_dir, save_dir)
        
##################################
# MODEL HANDLING
##################################

def save_model(models_dir, model_name, saver, sess):
    saver.save(sess, os.path.join(os.path.join(models_dir, model_name), model_name))

def load_model(models_dir, model_name, saver, sess):
    model_path = os.path.join(models_dir, model_name)
    meta_file = model_name + '.meta'
    meta_file_path = os.path.join(model_path, meta_file)
    saver = tf.train.import_meta_graph(meta_file_path)
    saver.restore(sess, os.path.join(model_path, model_name))
    