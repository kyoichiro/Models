#coding:utf-8

import argparse
import numpy as np
import chainer
from chainer import Function, Variable
from chainer import cuda, optimizers, serializers, utils
from chainer import Link, Chain, ChainList
import chainer.functions as F
import chainer.links as L
from sklearn.datasets import fetch_mldata
from math import log

import matplotlib.pyplot as plt
import gzip
import sys

N = 60000
k = 1
n_epoch = 1000
batchsize = 100

input_units = 784
n_units = 256
n2_units = 64
output_units = 1

g_input_units = 100
g_n_units = 256 #1200
g_n2_units = 512 #1200
g_output_units = 784

class Generator(Chain):
	def __init__(self):
		super(Generator, self).__init__(
			gl1=L.Linear(g_input_units, g_n_units),
			#gl2=L.Linear(g_n_units, g_n2_units),
			#gl3=L.Linear(g_n2_units, g_output_units),
			gl2=L.Linear(g_n_units, g_output_units),

			bn1 = L.BatchNormalization(size=g_n_units, use_gamma=False),
			bn2 = L.BatchNormalization(size=g_n2_units, use_gamma=False),
			bn3 = L.BatchNormalization(size=g_output_units, use_gamma=False),
		)

	def __call__(self, x):
		h1=F.relu(self.bn1(self.gl1(x)))
		#h2=F.relu(self.bn2(self.gl2(h1)))
		#y=F.dropout(F.sigmoid(self.gl2(h1))) #dropoutによって画像が荒くなる可能性あり
		y=F.sigmoid(self.gl2(h1))
		return y

class Discriminator(Chain):
	def __init__(self):
		super(Discriminator, self).__init__(
			dl1=L.Linear(input_units, n_units),
			#dl2=L.Linear(n_units, n2_units),
			#dl3=L.Linear(n2_units, output_units),
			dl2=L.Linear(n_units, output_units),

			bn1 = L.BatchNormalization(size=n_units, use_gamma=False),
			bn2 = L.BatchNormalization(size=n2_units, use_gamma=False),
		)

	def __call__(self, x):
		h1=F.leaky_relu(self.bn1(self.dl1(x)))
		#h2=F.leaky_relu(self.bn2(self.dl2(h1)))
		y=F.leaky_relu(self.dl2(h1))
		return y

def draw_digit3(data, n):
	plt.subplot(10, 10, n)
	data = data[::-1]
	plt.xlim(0, 27)
	plt.ylim(0, 27)
	plt.pcolor(data)
	plt.gray()
	plt.tick_params(labelbottom = "off")
	plt.tick_params(labelleft = "off")

if __name__ == "__main__":

	parser = argparse.ArgumentParser()
	parser.add_argument('--gpu', '-g', default=-1, type=int,
                    help='GPU ID (negative value indicates CPU)')
	args = parser.parse_args()

	#setup models 
	Generator = Generator()
	Discriminator = Discriminator()
	opt_gene = optimizers.Adam()
	opt_dis = optimizers.Adam()
	opt_gene.setup(Generator)
	opt_dis.setup(Discriminator)

	if args.gpu >= 0:
		gpu_device = 0
		cuda.get_device(gpu_device).use()
		Generator.to_gpu(gpu_device)
		Discriminator.to_gpu(gpu_device)
		xp = cuda.cupy
	else:
		xp = np
	
	test_loss = []
	test_loss_gene  = []

	dl1_W = []
	dl2_W = []
	dl3_W = []

	print("start:import MNIST")

	mnist = fetch_mldata('MNIST original', data_home=".")

	print("end:import MNIST")

	#mnist.data : 70,000件の28x28=784次元ベクトルデータ
	mnist.data = mnist.data.astype(xp.float32)
	mnist.data /= 255  # 正規化
	mnist.target = mnist.target.astype(xp.int32)

	x_train, x_test = np.split(mnist.data,   [N])
	y_train, y_test = np.split(mnist.target, [N])
	N_test = y_test.size

	x_train = xp.array(x_train)
	x_test = xp.array(x_test)
	y_train = xp.array(y_train)
	y_test = xp.array(y_test)

	# Learning loop
	for epoch in range(1, n_epoch+1):
		print("epoch: "+ str(epoch))

		# training
		# N個の順番をランダムに並び替える
		perm = np.random.permutation(N)
		sum_accuracy = 0
		sum_loss = 0

		# 0〜Nまでのデータをバッチサイズごとに使って学習
		for i in range(0, N, batchsize):
			x_batch = x_train[perm[i:i+batchsize]]
			y_batch = y_train[perm[i:i+batchsize]]
			x_batch, y_batch = Variable(x_batch), Variable(y_batch)

			x_noise = xp.array([[np.random.uniform(-1, 1, g_input_units)] for i in range(batchsize)]).astype(xp.float32) #分布は[-1,1]が良い(経験)
			x_noise = Variable(x_noise)

			# 勾配を初期化
			Generator.zerograds()
			Discriminator.zerograds()

			#Generatorへの入力(Make image)
			x_generator = Generator(x_noise)
			x_image = cuda.to_cpu(x_generator.data)
			x_image = x_image.reshape(batchsize,28,28)
            
            #Input each Network
			Dis = Discriminator(x_batch)
			Dis_from_gene = Discriminator(x_generator)

			# 順伝播させて誤差と精度を算出
			loss_dis=0
			loss_gene=0

			loss_dis = F.sum(F.sigmoid_cross_entropy(Dis, xp.ones((batchsize,output_units), dtype = xp.int32), normalize = False))/batchsize + F.sum(F.sigmoid_cross_entropy((1-Dis_from_gene), xp.ones((batchsize, output_units), dtype = xp.int32), normalize = False))/batchsize 
			# 誤差逆伝播で勾配を計算
			loss_dis.backward()
			opt_dis.update()

			#Generatorの学習
			if i%k == 0:
				loss_gene = F.sum(F.sigmoid_cross_entropy(Dis_from_gene, xp.ones((batchsize, output_units), dtype = xp.int32), normalize = False))/batchsize
				#loss_gene -= F.sum(F.sigmoid_cross_entropy((1-Dis_from_gene), xp.ones((batchsize, output_units), dtype = xp.int32), normalize = False))/batchsize
				loss_gene.backward()
				opt_gene.update()

		# 訓練データの誤差と、正解精度を表示
		print ("train mean loss={}".format(loss_dis.data))
		print ("generator mean loss={}".format(loss_gene.data))
		#plt.imshow(x_image[0]*255)
		#plt.gray()
		#plt.savefig("./GAN_2-result/Epoch{}".format(epoch))

		#evaluation
		#テストデータで誤差と、正解精度を算出し汎化性能

		test_loss.append(loss_dis.data)
		test_loss_gene.append(loss_gene.data)

		plt.figure(figsize = (15, 15))

		cnt = 0
		for idx in np.random.permutation(batchsize)[:100]:
			cnt += 1
			draw_digit3(x_image[idx]*255, cnt)
		plt.savefig("./GAN_2-result/Epoch{}".format(epoch))

		# 学習したパラメーターを保存
		#dl1_W.append(Discriminator.dl1.W)
		#dl2_W.append(Discriminator.dl2.W)
		#dl3_W.append(Discriminator.dl3.W)
    
	# 精度と誤差をグラフ描画
	plt.figure(figsize=(8,6))
	plt.plot(range(len(test_loss)),test_loss,color = red)
	plt.plot(range(len(test_loss_gene)), test_loss_gene, color = blue)
	plt.legend(["train_acc","test_acc"],loc=4)
	plt.title("Accuracy of digit recognition.")
	plt.plot()
	plt.savefig("./GAN_2-reslut/Train_error")

	print("End program")
