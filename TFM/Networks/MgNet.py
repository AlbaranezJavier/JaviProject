from tensorflow.keras.layers import Conv2D, concatenate, BatchNormalization, Conv2DTranspose
from tensorflow.keras.regularizers import L2
import numpy as np
from tensorflow.keras import Model, Input
import cv2, glob
from tensorflow import keras, random_normal_initializer, Variable, zeros_initializer
import tensorflow as tf

'''
This script contains the proposed network structures.
'''


class Filters:
    def __init__(self, type, out_channels):
        if type == "border":
            filter = np.array([[[[0]], [[-1]], [[0]]],
                               [[[-1]], [[4]], [[-1]]],
                               [[[0]], [[-1]], [[0]]]])
            self.strides = [1, 1, 1, 1]
            self.pad = "SAME"
        elif type == "bilinear":
            filter = np.array([[[[.25]], [[.5]], [[.25]]],
                               [[[.5]], [[1]], [[.5]]],
                               [[[.25]], [[.5]], [[.25]]]])
            self.strides = [1, 2, 2, 1]
            self.pad = [[0, 0], [1, 1], [1, 1], [0, 0]]
        elif type == "linear":
            filter = np.array([[[[0]], [[.5]], [[.5]]],
                               [[[.5]], [[1]], [[.5]]],
                               [[[.5]], [[.5]], [[0]]]])
            self.strides = [1, 1, 1, 1]
            self.pad = [[0, 0], [1, 1], [1, 1], [0, 0]]
        elif type == "average":
            filter = np.array([[[[1 / 9]], [[1 / 9]], [[1 / 9]]],
                               [[[1 / 9]], [[1 / 9]], [[1 / 9]]],
                               [[[1 / 9]], [[1 / 9]], [[1 / 9]]]])
            self.strides = [1, 1, 1, 1]
            self.pad = [[0, 0], [1, 1], [1, 1], [0, 0]]
        else:
            raise Exception("In Conv2d_fixed select: border, bilinear, linear or average.")

        self.filter = np.repeat(filter.astype(np.float32), [out_channels], axis=3)


class Conv2DFixed(keras.layers.Layer, Filters):
    def __init__(self, kernel_type, out_channels):
        super(Conv2DFixed, self).__init__()
        Filters.__init__(self, kernel_type, out_channels)
        self.w = tf.Variable(initial_value=tf.constant(self.filter, dtype=tf.float32), trainable=False)
        self.bn = BatchNormalization()

    def call(self, inputs):
        channels = tf.nn.conv2d(inputs, self.w, strides=self.strides, padding=self.pad)
        norm = self.bn(channels)
        return norm


class Conv2DFixed_Transpose(keras.layers.Layer, Filters):
    def __init__(self, kernel_type, out_shape):
        super(Conv2DFixed_Transpose, self).__init__()
        Filters.__init__(self, kernel_type, out_shape[3])
        self.out_shape = out_shape
        self.w = tf.Variable(initial_value=tf.constant(self.filter, dtype=tf.float32), trainable=False)
        self.bn = BatchNormalization()

    def call(self, inputs):
        channels = tf.nn.conv2d_transpose(inputs, self.w, output_shape=self.out_shape, strides=self.strides,
                                          padding=self.pad)
        norm = self.bn(channels)
        return norm


class Conv2D_NA(keras.layers.Layer):
    def __init__(self, k_dim, output_channel, stride, padding='VALID', k_reg=None):
        super(Conv2D_NA, self).__init__()
        self.stride = stride
        self.padding = padding

        self.conv = Conv2D(filters=output_channel, kernel_size=(k_dim, k_dim), strides=(stride, stride),
                           padding=padding, kernel_regularizer=k_reg)
        self.bn = BatchNormalization()

    def call(self, inputs):
        channels = self.conv(inputs)
        norm = self.bn(channels)
        return tf.nn.relu(norm + self.conv.bias)


class Mg_Block(keras.layers.Layer):
    def __init__(self, k_dim, output_channel, k_reg=None, **kwargs):
        super(Mg_Block, self).__init__(**kwargs)

        # Data-feature mapping
        self.a1 = Conv2D(filters=3, kernel_size=(k_dim, k_dim), strides=(1, 1),
                         padding='SAME', kernel_regularizer=k_reg, name="a1")
        self.a2 = Conv2D(filters=3, kernel_size=(k_dim, k_dim), strides=(1, 1),
                         padding='SAME', kernel_regularizer=k_reg, name="a2")
        self.a3 = Conv2D(filters=3, kernel_size=(k_dim, k_dim), strides=(1, 1),
                         padding='SAME', kernel_regularizer=k_reg, name="a3")
        self.a4 = Conv2D(filters=3, kernel_size=(k_dim, k_dim), strides=(1, 1),
                         padding='SAME', kernel_regularizer=k_reg, name="a4")

        # Feature extractor
        self.b1 = Conv2D(filters=output_channel, kernel_size=(k_dim, k_dim), strides=(1, 1),
                         padding='SAME', kernel_regularizer=k_reg, name="b1")
        self.b2 = Conv2D(filters=output_channel, kernel_size=(k_dim, k_dim), strides=(1, 1),
                         padding='SAME', kernel_regularizer=k_reg, name="b2")
        self.b3 = Conv2D(filters=output_channel, kernel_size=(k_dim, k_dim), strides=(1, 1),
                         padding='SAME', kernel_regularizer=k_reg, name="b3")
        self.b4 = Conv2D(filters=output_channel, kernel_size=(k_dim, k_dim), strides=(1, 1),
                         padding='SAME', kernel_regularizer=k_reg, name="b4")

        # Interpolator
        self.i2 = Conv2D(filters=output_channel, kernel_size=(k_dim, k_dim), strides=(2, 2),
                         padding='SAME', kernel_regularizer=k_reg, name="i2")
        self.i3 = Conv2D(filters=output_channel, kernel_size=(k_dim, k_dim), strides=(2, 2),
                         padding='SAME', kernel_regularizer=k_reg, name="i3")
        self.i4 = Conv2D(filters=output_channel, kernel_size=(k_dim, k_dim), strides=(2, 2),
                         padding='SAME', kernel_regularizer=k_reg, name="i4")

        # Restrictor
        self.r = Conv2DFixed("bilinear", 3)

        self.bn_a = BatchNormalization()
        self.bn = BatchNormalization()

    def call(self, f):
        # Level 1
        # - Smoothing
        a = f - self.bn_a(self.a1(tf.zeros_like(f)))
        u1 = tf.nn.relu(self.bn(self.b1(tf.nn.relu(a))))
        for i in range(3):
            a = f - self.bn_a(self.a1(u1))
            b = tf.nn.relu(self.bn(self.b1(tf.nn.relu(a))))
            u1 = u1 + b

        # - Interpolation and restriction
        u2 = self.i2(u1)
        _a = self.bn_a(self.a2(u2))
        _f2 = self.r(a) + _a

        # Level 2
        # - Smoothing
        a = _f2 - _a
        b = tf.nn.relu(self.bn(self.b2(tf.nn.relu(a))))
        u2 = b + u2
        for i in range(3):
            a = f - self.bn_a(self.a2(u2))
            b = tf.nn.relu(self.bn(self.b2(tf.nn.relu(a))))
            u2 = u2 + b

        # - Interpolation and restriction
        u3 = self.i3(u2)
        _a = self.bn_a(self.a3(u3))
        _f3 = self.r(a) + _a

        # Level 3
        # - Smoothing
        a = _f3 - _a
        b = tf.nn.relu(self.bn(self.b3(tf.nn.relu(a))))
        u3 = b + u3
        for i in range(3):
            a = f - self.bn_a(self.a3(u3))
            b = tf.nn.relu(self.bn(self.b3(tf.nn.relu(a))))
            u3 = u3 + b

        # - Interpolation and restriction
        u4 = self.i4(u3)
        _a = self.bn_a(self.a4(u4))
        _f4 = self.r(a) + _a

        # Level 4
        # - Smoothing
        a = _f4 - _a
        b = tf.nn.relu(self.bn(self.b4(tf.nn.relu(a))))
        u4 = b + u4
        for i in range(3):
            a = f - self.bn_a(self.a4(u4))
            b = tf.nn.relu(self.bn(self.b4(tf.nn.relu(a))))
            u4 = u4 + b

        return u1, f, u2, _f2, u3, _f3, u4, _f4


class Mg_Cycle(keras.layers.Layer):
    def __init__(self, k_dim, output_size, k_reg=None):
        super(Mg_Cycle, self).__init__()

        # Data-feature mapping
        self.a = Conv2D(filters=3, kernel_size=(k_dim, k_dim), strides=(1, 1),
                             padding='SAME', kernel_regularizer=k_reg)

        # Feature extractor
        self.b = Conv2D(filters=output_size[3], kernel_size=(k_dim, k_dim), strides=(1, 1),
                        padding='SAME', kernel_regularizer=k_reg)

        # Prolongator
        self.p = Conv2DFixed_Transpose("bilinear", output_size)

        self.bn_a = BatchNormalization()
        self.bn = BatchNormalization()

    def call(self, u_prev, u_post, f, v, u=None):
        # Prolongation and correction
        if u == None:
            _u = u_prev + self.p(-u_post)
        else:
            _u = u_prev + self.p(u - u_post)
        # Post-smoothing
        for i in range(v):
            a = self.bn_a(self.a(_u))
            b = tf.nn.relu(self.bn(self.b(tf.nn.relu(f - a))))
            _u = _u + b
        return _u


class Net_test(Model):
    def __init__(self):
        super(Net_test, self).__init__()
        # self.l_720 = Conv2DFixed("border", 3)
        # self.l_720 = Conv2DFixed("bilinear", 3)
        # self.d_720 = Conv2DFixed_Transpose("bilinear", [1, 720, 1280, 3])
        # self.l_720 = Conv2DFixed("linear", 3)
        self.l_720 = Conv2DFixed("average", 3)

    def call(self, inputs):
        x = self.l_720(inputs)
        # x = self.d_720(x)
        return x


def MgNet_0(f, batch, learn_reg=1e-2):
    # Variables
    l2 = L2(learn_reg)

    # Block
    u1, f1, u2, f2, u3, f3, u4, f4 = Mg_Block(k_dim=3, output_channel=5, k_reg=l2)(f)

    # - Cycle 3
    u = Mg_Cycle(k_dim=3, output_size=[batch, 129, 257, 5], k_reg=l2)(u_prev=u3, u_post=u4, f=f3, v=3)

    # - Cycle 2
    u = Mg_Cycle(k_dim=3, output_size=[batch, 257, 513, 5], k_reg=l2)(u_prev=u2, u_post=u3, f=f2, v=3, u=u)

    # - Cycle 1
    u = Mg_Cycle(k_dim=3, output_size=[batch, 513, 1025, 5], k_reg=l2)(u_prev=u1, u_post=u2, f=f1, v=3, u=u)

    # Out
    u = Conv2D(filters=5, kernel_size=(1, 1), strides=(1, 1), padding='SAME', kernel_regularizer=l2,
               activation="softmax")(u)

    return u


class Mg(keras.layers.Layer):
    def __init__(self, size, output_channel, batch, **kwargs):
        super(Mg, self).__init__(**kwargs)

        # Data
        u_init = tf.zeros_initializer()
        self.u1 = tf.Variable(initial_value=u_init(shape=[batch, size[0], size[1], output_channel], dtype="float32"))
        self.u2 = tf.Variable(initial_value=u_init(shape=[batch, size[0] // 2 + 1, size[1] // 2 + 1, output_channel],
                                                   dtype="float32"))
        self.u3 = tf.Variable(initial_value=u_init(shape=[batch, size[0] // 4 + 1, size[1] // 4 + 1, output_channel],
                                                   dtype="float32"))
        self.u4 = tf.Variable(initial_value=u_init(shape=[batch, size[0] // 8 + 1, size[1] // 8 + 1, output_channel],
                                                   dtype="float32"))

    def build(self, input_shape):
        # Data-feature mapping
        self.a1_prev = Conv2D(filters=5, kernel_size=(3, 3), strides=(1, 1),
                              padding='SAME', kernel_regularizer=L2(1e-2), activation="relu")
        self.f_exp = Conv2D(filters=5, kernel_size=(3, 3), strides=(1, 1),
                            padding='SAME', kernel_regularizer=L2(1e-2), activation="relu")
        self.a2_prev = Conv2D(filters=5, kernel_size=(3, 3), strides=(1, 1),
                              padding='SAME', kernel_regularizer=L2(1e-2), activation="relu")
        self.a3_prev = Conv2D(filters=5, kernel_size=(3, 3), strides=(1, 1),
                              padding='SAME', kernel_regularizer=L2(1e-2), activation="relu")
        self.a4_prev = Conv2D(filters=5, kernel_size=(3, 3), strides=(1, 1),
                              padding='SAME', kernel_regularizer=L2(1e-2), activation="relu")
        self.a1_post = Conv2D(filters=5, kernel_size=(3, 3), strides=(1, 1),
                              padding='SAME', kernel_regularizer=L2(1e-2))
        self.a2_post = Conv2D(filters=5, kernel_size=(3, 3), strides=(1, 1),
                              padding='SAME', kernel_regularizer=L2(1e-2))
        self.a3_post = Conv2D(filters=5, kernel_size=(3, 3), strides=(1, 1),
                              padding='SAME', kernel_regularizer=L2(1e-2))
        self.a4_post = Conv2D(filters=5, kernel_size=(3, 3), strides=(1, 1),
                              padding='SAME', kernel_regularizer=L2(1e-2))

        # Feature extractor
        self.b1 = Conv2D(filters=5, kernel_size=(3, 3), strides=(1, 1),
                         padding='SAME', kernel_regularizer=L2(1e-2))
        self.b2 = Conv2D(filters=5, kernel_size=(3, 3), strides=(1, 1),
                         padding='SAME', kernel_regularizer=L2(1e-2))
        self.b3 = Conv2D(filters=5, kernel_size=(3, 3), strides=(1, 1),
                         padding='SAME', kernel_regularizer=L2(1e-2))
        self.b4 = Conv2D(filters=5, kernel_size=(3, 3), strides=(1, 1),
                         padding='SAME', kernel_regularizer=L2(1e-2))

        # Interpolator
        self.i2 = Conv2D(filters=5, kernel_size=(3, 3), strides=(2, 2),
                         padding='SAME', kernel_regularizer=L2(1e-2))
        self.i3 = Conv2D(filters=5, kernel_size=(3, 3), strides=(2, 2),
                         padding='SAME', kernel_regularizer=L2(1e-2))
        self.i4 = Conv2D(filters=5, kernel_size=(3, 3), strides=(2, 2),
                         padding='SAME', kernel_regularizer=L2(1e-2))

        # Restrictor
        self.r = Conv2DFixed("bilinear", 5)

        self.bn = BatchNormalization()

    def call(self, f):
        # Level 1
        # - Smoothing
        _f1 = self.f_exp(f)
        a = self.bn(_f1 - self.a1_post(self.a1_prev(self.u1)))
        b = self.bn(tf.nn.relu(self.b1(tf.nn.relu(a))))
        self.u1.assign(b + self.u1)

        # - Interpolation and restriction
        self.u2 = self.i2(self.u1)
        _a = self.bn(self.a2_post(self.a2_prev(self.u2)))
        _f2 = self.r(a) + _a

        # Level 2
        # - Smoothing
        a = self.bn(_f2 - _a)
        b = self.bn(tf.nn.relu(self.b2(tf.nn.relu(a))))
        self.u2 = b + self.u2
        # - Interpolation and restriction
        self.u3 = self.i3(self.u2)
        _a = self.bn(self.a3_post(self.a3_prev(self.u3)))
        _f3 = self.r(a) + _a
        # Level 3
        # - Smoothing
        a = self.bn(_f3 - _a)
        b = self.bn(tf.nn.relu(self.b3(tf.nn.relu(a))))
        self.u3 = b + self.u3
        # - Interpolation and restriction
        self.u4 = self.i4(self.u3)
        _a = self.bn(self.a4_post(self.a4_prev(self.u4)))
        _f4 = self.r(a) + _a
        # Level 4
        # - Smoothing
        a = self.bn(_f4 - _a)
        b = self.bn(tf.nn.relu(self.b4(tf.nn.relu(a))))
        self.u4 = b + self.u4
        return self.u1  # , _f1, self.u2, _f2, self.u3, _f3, self.u4, _f4


if __name__ == '__main__':
    path_img = glob.glob(r"C:\Users\TTe_J\Downloads\new_RGBs\vid_2_frame_1708.jpg")
    img = cv2.cvtColor(cv2.imread(path_img[0]), cv2.COLOR_BGR2HLS).astype(np.float32) / 255.
    # model = Net_0(batch=1)
    model = Net_test()
    model.build(input_shape=(1, 720, 1280, 3))
    model.summary()
    x = model(np.expand_dims(img, 0))
    print(x.shape)
    cv2.imshow("h_conv", x.numpy()[0, ..., 0])
    cv2.waitKey(0)
    cv2.imshow("s_conv", x.numpy()[0, ..., 1])
    cv2.waitKey(0)
    cv2.imshow("v_conv", x.numpy()[0, ..., 2])
    cv2.waitKey(0)
    cv2.imshow("h", img[..., 0])
    cv2.waitKey(0)
    cv2.imshow("s", img[..., 1])
    cv2.waitKey(0)
    cv2.imshow("v", img[..., 2])
    cv2.waitKey(0)
    cv2.destroyAllWindows()
