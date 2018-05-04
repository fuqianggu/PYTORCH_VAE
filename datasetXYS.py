import xml.etree.ElementTree as ET
import numpy as np
import os 
import copy
import random

import torch
import torch.nn as nn
import torch.nn.functional as F
from torchvision import transforms
from torch.utils.data import Dataset

import cv2

def randomizeBackground(img) :
	background_color = img[0,0]
	mask = np.array(img == background_color,dtype=np.uint8)
	random_background = np.random.randint(255, size=img.shape,dtype=np.uint8)
	ret = img*(1-mask)+random_background*mask 
	return ret

class RandomRecolorNormalize(object) :
	def __init__(self,sizew=224,sizeh=224) :
		self.sizeh = sizeh
		self.sizew = sizew

	def __call__(self,sample) :
		img, gaze = sample['image'], sample['gaze']
		h,w,c = img.shape

		
		#recolor :
		t = [np.random.uniform()]
		t += [np.random.uniform()]
		t += [np.random.uniform()]
		t = np.array(t)

		img = img * (1+t)

		# Normalize color between 0 and 1 :
		#img = img / (255.0*1.0)

		# Normalize the size of the image :
		#img = cv2.resize(img, (self.sizeh,self.sizew))

		return {'image':img, 'gaze':gaze}


class data2loc(object) :
	def __call__(self,sample) :
		img, gaze = sample['image'], sample['gaze']
		h,w,c = img.shape

		outputs = np.zeros((1,2))

		outputs[0,0] = gaze['x']
		outputs[0,1] = gaze['y']
				
			
		return {'image':img, 'gaze':outputs}


class ToTensor(object) :
	def __call__(self, sample) :
		image, outputs = sample['image'], sample['gaze']
		#swap color axis :
		# numpy : H x W x C
		# torch : C x H x W
		image = image.transpose( (2,0,1) )
		return {'image':torch.from_numpy(image/255.0), 'gaze':torch.from_numpy(outputs) }

Transform = transforms.Compose([
							data2loc(),
							ToTensor()
							])

TransformPlus = transforms.Compose([
							RandomRecolorNormalize(),
							data2loc(),
							ToTensor()
							])


def parse_annotation_GazeRecognition(ann_dir) :
	imgs = []

	folder = os.listdir(ann_dir)
	nbrann = len(folder)
	for idx_ann, ann in enumerate( folder ) :
		img = {}

		path2ann = os.path.join(ann_dir,ann)
		tree = ET.parse(path2ann )
		
		print('DATASET :: LOADING : {:0.1f} %'.format( idx_ann/nbrann*100.0), end='\r', flush=True )

		for elem in tree.iter() :
			if 'filename' in elem.tag :
				imgs += [img]
				img['filename'] = elem.text

			if 'width' in elem.tag :
				img['width'] = int(float(elem.text))
			if 'height' in elem.tag :
				img['height'] = int(float(elem.text))
			
			if 'data' in elem.tag:
				data = {}
				img['data'] = data
				
				for attr in list(elem) :
					if 'model' in attr.tag :
						data['model'] = attr.text
					if 'gaze_position' in attr.tag :
						gaze = {}
						data['gaze'] = gaze
						
						for attri in list(attr) :
							if 'x' in attri.tag :
								gaze['x'] = float(attri.text)
							if 'y' in attri.tag :
								gaze['y'] = float(attri.text)
					if 'screen_size' in attr.tag :
						screen = {}
						data['screen'] = screen
						
						for attri in list(attr) :
							if 'width' in attri.tag :
								screen['width'] = float(attri.text)
							if 'height' in attri.tag :
								screen['height'] = float(attri.text)
					if 'camera_screen' in attr.tag :
						cam_screen = {}
						data['camera_screen_center_offset'] = cam_screen
						
						for attri in list(attr) :
							if 'x' in attri.tag :
								cam_screen['x'] = float(attri.text)
							if 'y' in attri.tag :
								cam_screen['y'] = float(attri.text)
					if 'head' in attr.tag :
						head = {}
						data['head'] = head

						for attri in list(attr) :
							if 'head_camera_distance' in attri.tag :
								head['head_camera_distance'] = float(attri.text)

			if 'object' in elem.tag:
				name = None
				bndbox = [0,0,0,0]

				for attr in list(elem) :
					if 'name' in attr.tag :
						name = attr.text
					if 'bndbox' in attr.tag :
						for attri in list(attr) :
							if 'xmin' in attri.tag :
								bndbox[0] = float(attri.text)
							if 'ymin' in attri.tag :
								bndbox[1] = float(attri.text)
							if 'xmax' in attri.tag :
								bndbox[2] = float(attri.text)
							if 'ymax' in attri.tag :
								bndbox[3] = float(attri.text)
				
				if name is not None :
					img[name] = bndbox
				
						
					
	return imgs



class DatasetGazeRecognition(Dataset) :
	def __init__(self,img_dir,ann_dir,width=224,height=224,transform=TransformPlus,stacking=False,divide2=False,randomcropping=True):
		super(DatasetGazeRecognition,self).__init__()
		self.img_dir = img_dir
		self.ann_dir = ann_dir
		self.stacking = stacking
		self.divide2 = divide2
		self.randomcropping = randomcropping

		self.testing = False
		#self.nbrTestModels = 4
		self.nbrTestModels = 1
		self.testsize = 0
		self.testoffset = 0

		self.w = width
		self.h = height

		self.parsedAnnotations = parse_annotation_GazeRecognition(self.ann_dir)

		self.transform = transform
		#default transformations :
		# ...
		# -2 : data2loc : transform the data list of dictionnaries into usable numpy outputs  
		# -1 : ToTensor

		self.idxModels = dict()
		for idx in range( len(self) ) :
			model = self.parsedAnnotations[idx]['data']['model']
			if not( model in self.idxModels.keys() ) :
				self.idxModels[model] = list()
			self.idxModels[model].append(idx)

		self.idx2model = list(self.idxModels.keys())

		for model in self.idxModels.keys() :
			print('Model : {} :: {} pictures.'.format(model, len(self.idxModels[model]) ) )

		self.testsize = sum( [len(self.idxModels[ self.idx2model[model] ]) for model in range( len(self.idxModels)-self.nbrTestModels,len(self.idxModels) )])
		self.testoffset = len(self.parsedAnnotations)-self.testsize
		print('TESTING SIZE : {}'.format(self.testsize))

	def __len__(self) :
		if not(self.testing):
			ret = len(self.parsedAnnotations)-self.testsize
			if ret == 0 :
				ret = self.testsize
			return ret 
		else :
			return self.testsize

	def nbrTasks(self) :
		return len(self.idxModels.keys())

	def nbrSample4Task(self,model_idx) :
		return len(self.idxModels[ self.idx2model[model_idx] ] )

	def generateFewShotLearningTask(self, task_idx, nbrSample=100) :
		model_idx = task_idx
		nbrSample = min( nbrSample, self.nbrSample4Task(model_idx) )
		indexes = self.idxModels[ self.idx2model[model_idx] ]
		
		random.shuffle(indexes)

		samples = list()
		for m in range(nbrSample) :
			samples.append( {'model':model_idx, 'sample':indexes[m]} )

		random.shuffle(samples)

		return samples, nbrSample

	def getDummyLabel(self) :
		randidx = np.random.randing(len(self))
		return self[randidx]['gaze']

	def generateIterFewShotInputSequence(self, task_idx, nbrSample=100) :
		model_idx = task_idx
		'''
		Returns :
		    sequence of tuple (x_0, y_{-1}(dummy)), (x_1, y_0) ... (x_n, y_n-1), (x_n+1(dummy), y_n)
		    nbr of samples in the whole task.
		'''
		samples, nbrSamples = self.generateFewShotLearningTask(task_idx=model_idx, nbrSample=nbrSample)

		seq = list()
		prev_sample = self[ samples[-1]['sample'] ]
		curr_sample = None 
		for i in range(nbrSamples) :
			d = dict()
			curr_sample = self[ samples[i]['sample'] ]

			x = curr_sample['image']
			y = prev_sample['gaze']
			label = curr_sample['gaze']

			d = {'x':x, 'y':y, 'label':label}
			seq.append( d )

			prev_sample = curr_sample

		return seq, nbrSamples

	def generateIterFewShotInputSequenceBatched(self, task_idx, nbrSample=100, batch_size=1) :
		model_idx = task_idx
		'''
		Returns :
		    sequence of tuple (x_0, y_{-1}(dummy)), (x_1, y_0) ... (x_n, y_n-1), (x_n+1(dummy), y_n)
		    nbr of batch samples in the whole task.
		'''
		samples, nbrSamples = self.generateFewShotLearningTask(task_idx=model_idx, nbrSample=nbrSample)

		nbrSample4Task = nbrSample // batch_size

		seq = list()
		#prev_sample = self[ samples[-1]['sample'] ]
		prev_sample = torch.cat( [ self[ samples[-1]['sample'] ]['gaze'] ] * batch_size, dim=0)
		curr_sample = None 
		#for i in range(nbrSamples) :
		for i in range(nbrSample4Task) :
			d = dict()
			for j in range(batch_size) :
				idx = j+i*batch_size
				#curr_sample = self[ samples[i]['sample'] ]
				curr_sample = self[ samples[idx]['sample'] ]

				x = curr_sample['image'].unsqueeze(0)
				#y = prev_sample['gaze']
				y = prev_sample[j].unsqueeze(0)
				label = curr_sample['gaze']

				if len(d.keys()) == 0 :
					d = {'x':x, 'y':y, 'label':label}
				else :
					d['x'] = torch.cat( [d['x'], x], dim=0)
					d['y'] = torch.cat( [d['y'], y], dim=0)
					d['label'] = torch.cat( [d['label'], label], dim=0)
			
			seq.append( d )

			prev_sample = d['label']

		#return seq, nbrSamples
		return seq, nbrSample4Task

	def getSample(self, task_idx, sample_idx) :
		model_idx = task_idx
		model_name = self.idx2model[model_idx]
		idxsample = self.idxModels[model_name][sample_idx]
		sample = self[idxsample]

		return sample

	def __getitem__(self,idx) :
		if self.testing :
			idx = idx%self.testsize
			idx = idx + self.testoffset

		issue = True
		while issue :
			try :
				path = os.path.join(self.img_dir,self.parsedAnnotations[idx]['filename']+'.png' )
				img = cv2.imread(path)
				img = randomizeBackground(img)
				h,w,c = img.shape 
				issue = False
			except Exception as e :
				print(e,idx)
				idx = idx+1
					

		if self.stacking :
			img = img#np.expand_dims( cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), 2)

			face_bndbox = self.parsedAnnotations[idx]['face']
			reye_bndbox = self.parsedAnnotations[idx]['reye']
			leye_bndbox = self.parsedAnnotations[idx]['leye']
			
			scalar = 1.0
			if self.divide2 :
				scalar = 2.0
			
			# face :
			fy1 = int( min( max(0,face_bndbox[1]/scalar), h) )
			fy2 = int( min( max(0,face_bndbox[3]/scalar), h) )
			fx1 = int( min( max(0,face_bndbox[0]/scalar), w) )
			fx2 = int( min( max(0,face_bndbox[2]/scalar), w) )
			
			face_img = img[fy1:fy2, fx1:fx2,:]
			#face_img = np.expand_dims(  cv2.resize(face_img, (w,h) ), 2)
			face_img = cv2.resize(face_img, (w,h) )
			
			# reye :
			ry1 = int( min( max(0,reye_bndbox[1]/scalar), h) )
			ry2 = int( min( max(0,reye_bndbox[3]/scalar), h) )
			rx1 = int( min( max(0,reye_bndbox[0]/scalar), w) )
			rx2 = int( min( max(0,reye_bndbox[2]/scalar), w) )
			
			reye_img = img[ry1:ry2, rx1:rx2,:]
			# Random cropping over the eyes :
			if self.randomcropping:
				off = random.randint(1,64)
				ow, oh = w+off,h+off			
				reye_img = cv2.resize(reye_img, (ow,oh))
				top = np.random.randint(0, oh-h)
				left = np.random.randint(0, ow-w)
				reye_img = reye_img[top:top+h, left: left+w]
			#reye_img = np.expand_dims( cv2.resize(reye_img, (w,h) ), 2)
			reye_img = cv2.resize(reye_img, (w,h) )
				
			# leye :
			ly1 = int( min( max(0,leye_bndbox[1]/scalar), h) )
			ly2 = int( min( max(0,leye_bndbox[3]/scalar), h) )
			lx1 = int( min( max(0,leye_bndbox[0]/scalar), w) )
			lx2 = int( min( max(0,leye_bndbox[2]/scalar), w) )
			
			leye_img = img[ly1:ly2, lx1:lx2,:]
			# Random cropping over the eyes :
			if self.randomcropping:
				off = random.randint(1,64)
				ow, oh = w+off,h+off			
				leye_img = cv2.resize(leye_img, (ow,oh))
				top = np.random.randint(0, oh-h)
				left = np.random.randint(0, ow-w)
				leye_img = leye_img[top:top+h, left: left+w]
			#leye_img = np.expand_dims( cv2.resize(leye_img, (w,h) ), 2)
			leye_img = cv2.resize(leye_img, (w,h) )
			
			img = cv2.resize( img, (self.w, self.h) )
			reye_img = cv2.resize( reye_img, (self.w, self.h) )
			leye_img = cv2.resize( leye_img, (self.w, self.h) )


			# concatenation :
			#img = np.concatenate( [face_img, reye_img, leye_img], axis=2)
			img = np.concatenate( [img, reye_img, leye_img], axis=2)
		else :
			img = cv2.resize( img, (self.w, self.h) )

		img = np.ascontiguousarray(img)
		
		'''
		img = np.concatenate( [ img[:,:,idx:idx+3] for idx in [0,3,6] ], axis=0)
		cv2.imshow('test', img )
		while True :
			key = cv2.waitKey()
			if key == ord('q'):
				break
		'''
		gaze = copy.deepcopy(self.parsedAnnotations[idx]['data']['gaze'])
		cam_screen_offset = copy.deepcopy(self.parsedAnnotations[idx]['data']['camera_screen_center_offset'])
		for el in ['x','y'] :
			gaze[el] += cam_screen_offset[el]

		sample = {'image':img, 'gaze':gaze}

		if self.transform is not None :
			sample = self.transform(sample)

		return sample

	def generateVisualization(self, idx, shape=None, ratio=30, screen_size=[0.12,0.05],estimation=[0.02,0.02], cm_prec=0.02) :
		idx = int(idx)
		try :
			path = os.path.join(self.img_dir,self.parsedAnnotations[idx]['filename']+'.png' )
			img = cv2.imread(path)
			img = np.ascontiguousarray(img)
			
			gaze = copy.deepcopy(self.parsedAnnotations[idx]['data']['gaze'])
			cam_screen_offset = copy.deepcopy(self.parsedAnnotations[idx]['data']['camera_screen_center_offset'])
			for el in ['x','y'] :
				gaze[el] += cam_screen_offset[el]

			if shape is None :
				shape = list(img.shape)
			else :
				img = cv2.resize( img, shape)

			h,w,d = img.shape
			img = cv2.resize( img, (self.h, self.w) )
			# create visualization :
			visualization = 255*np.ones( (480,640,3), dtype=np.float32 )
			ratio = 640/(2*screen_size[1]*100)
			px_screen_size = np.array(screen_size) * 100 * ratio
			cam_offset = [-0.01,0.01]
			px_cam_offset = np.array(cam_offset) * 100 * ratio
			def draw_screen_cam(image,px_screen_size, px_cam_offset) :
				shape = np.array(image.shape)[0:2]
				offset = 10
				px_screen_offset = (shape - px_screen_size )/ 2
				pt1 = px_screen_offset
				pt2 = pt1+px_screen_size
				color = (0,0,0)

				pt1_t = (int(pt1[1])+offset,int(pt1[0]))
				pt2_t = (int(pt2[1])+offset,int(pt2[0]))
				cv2.rectangle(image, pt1_t, pt2_t, color=color, thickness=3)
				
				pt3 = pt1+px_cam_offset
				pt3_t = (int(pt3[1])+offset,int(pt3[0]))
				cv2.circle(image, pt3_t, radius=10, color=color, thickness=3)
				
				return image, pt3
			visualization, px_cam_pt = draw_screen_cam(visualization,px_screen_size,px_cam_offset)

			px_pt = np.array([ gaze['y'], gaze['x'] ]) * 100 * ratio
			px_estimation_pt = np.array(estimation) * 100 * ratio

			prec = int(cm_prec * 100 * ratio) 
			# 2 centimeter precision
			def draw_point(image,px_pt,prec,px_cam_pt,color=(255,255,255)) :
				pt = px_cam_pt+px_pt
				pt_t = ( int(pt[1]), int(pt[0]) )
				cv2.circle(image, pt_t, radius=prec, color=color, thickness=2)
				return image
			color_true = (0,255,0)
			visualization = draw_point(visualization,px_pt=px_pt,prec=4,px_cam_pt=px_cam_pt,color=color_true)
			color_est = (255,255,0)
			visualization = draw_point(visualization,px_pt=px_estimation_pt,prec=prec,px_cam_pt=px_cam_pt,color=color_est)

		except Exception as e :
			print(e)
			
		#if self.transform is not None :
		#	image = self.transform(image)
		#image = np.concatenate([image,visualization], axis=1)
		
		sample = {'image': img, 'visualization':visualization, 'gaze':gaze }
		
		return sample


class LinearClassifier(nn.Module) :
	def __init__(self, input_dim=10, output_dim=3) :
		super(LinearClassifier,self).__init__()

		self.input_dim = input_dim
		self.output_dim = output_dim

		self.fc = nn.Linear(self.input_dim,self.output_dim)

	def forward(self,x) :
		out = self.fc(x)
		soft_out = F.softmax(out)

		return soft_out

def test_error_visualization() :
	import matplotlib.pyplot as plt
	from mpl_toolkits.mplot3d import Axes3D

	def find_closest_2d(lt_2d,val2d) :
		def find_closest(lt,val,idx=-1,size=-1) :
			if size == -1 :
				size = len(lt)
				idx = size // 2 - 1

			if val <= lt[0] :
				return 0
			elif val >= lt[-1] :
				return len(lt)-1

			if size <= 1 :
				return idx
			else :
				size = size // 2
				print(idx,len(lt),size)
				d = abs(val-lt[idx])
				dm = abs(val-lt[idx-1])
				dp = abs(val-lt[idx+1])
				if dm <= d :
					return find_closest(lt,val,idx-size//2,size)
				elif dp <= d :
					return find_closest(lt,val,idx+size//2,size)
				else :
					return idx 

		lt = lt_2d[0]
		val = val2d[0]
		idx1 = find_closest(lt,val)
		lt = lt_2d[1]
		val = val2d[1]
		idx2 = find_closest(lt,val)
		
		return (idx1,idx2)

	dimx = 10
	dimy = 10
	x = [ [i/dimx for i in range(dimx)] for j in range(dimy)]
	y = [ [i/dimy for i in range(dimy)] for j in range(dimx)]

	
	lt_2d =[[i/dim for i in range(dim)] for dim in [dimx,dimy]]

	path = './vizdata.npz'
	data = np.load(path)

	
	gx = np.asarray(data['arr_0'])
	m = gx.mean()
	std = gx.std()
	gx = ( (gx-m)/std+1.0) /2.0
	gy = np.asarray(data['arr_1'])
	m = gy.mean()
	std = gy.std()
	gy = ( (gy-m)/std+1.0) /2.0
	meanerror = np.asarray(data['arr_2'])
	print(meanerror[0])
	
	def arrange(lt_2d,gx,gy,val,dimx=100,dimy=100) :
		nbrel = len(gx)
		out = [ [(0,0) for i in range(dimx)] for j in range(dimy)] 
		for i in range(nbrel) :
			idxx, idxy = find_closest_2d(lt_2d=lt_2d,val2d=[gx[i],gy[i]])
			it = out[idxy][idxx][0]
			cummean = out[idxy][idxx][1]
			out[idxy][idxx] = (it+1, (cummean*it + val[i]) / (it+1) ) 
		return out 

	meanerror = arrange(lt_2d=lt_2d, gx=gx, gy=gy, val=meanerror,dimx=dimx,dimy=dimy)
	
	'''
	x = [ [ x[j][i] for i in range(dimx) if meanerror[j][i][0] for j in range(dimy)] ).reshape((-1))
	xs = np.zeros( (len(x) ) )
	for i,el in enumerate(x) :
		xs[i] = el
	print(xs.shape)
	y = np.asarray( [ [y[j][i] for i in range(dimx) if meanerror[j][i][0]] for j in range(dimy)] ).reshape((-1))
	meanerror = np.asarray( [ [meanerror[j][i] for i in range(dimx) if meanerror[j][i][0]] for j in range(dimy)] ).reshape((-1))
	'''
	#x = x.reshape((-1))
	#y = y.reshape((-1))
	
	'''
	xs = list()
	ys = list()
	me = list()
	for i in range(dimx) :
		for j in range(dimy) :
			if meanerror[j][i][0] :
				me.append(meanerror[j][i][1])
				xs.append( x[i][j])
				ys.append( y[i][j])
	'''

	#meanerror = [ [i+np.random.rand() for i in range(dimx)] for j in range(dimy)]
	
	#print(x.shape)

	xs = np.arange(0,1,1.0/dimx)
	ys = np.arange(0,1,1.0/dimy)
	xs, ys = np.meshgrid(xs,ys)
	#me = np.sqrt(xs**2+ys**2)
	meanerror =  [ [meanerror[j][i][1] for i in range(dimx)] for j in range(dimy)] 
	
	print(meanerror)
	me = np.array( meanerror ).reshape( (dimx,dimy))
	mv = None
	it = 1
	for i in range(dimx) :
		for j in range(dimy) :
			if me[i][j] != 0 :
				if mv is None :
					mv = me[i][j]
				else :
					mv = (mv*it + me[i][j])/(it+1)
					it += 1

	for i in range(dimx) :
		for j in range(dimy) :
			if me[i][j] == 0 :
				me[i][j] = mv
	print(me.shape)
	
	print(xs)
	print('-'*20)
	print(ys)


	fig = plt.figure()
	ax = fig.add_subplot(111, projection='3d')
	#ax.scatter( xs=xs, ys=ys, zs=me)
	ax.plot_surface( X=xs, Y=ys, Z=me)
	plt.show()

def test_stacking() :
	#dataset = load_dataset_XYS(stacking=True)
	#dataset = load_dataset_XYSM10(stacking=True)
	#dataset = load_dataset_XYSM10_CXY_2(stacking=True)
	#dataset = load_dataset_XYSM10_CXY_E(stacking=True)
	dataset = load_dataset_XYSM2_C3D_EF(stacking=True)

	idx = 0 
	sample = dataset[0]

	img = sample['image']
	img0 = img[:,:,:].numpy().transpose((1,2,0))
	print(img0.shape)
	img0 = np.concatenate( [ img0[:,:,idx:idx+3] for idx in [0,3,6] ], axis=0)
		
	while True :
		cv2.imshow('test',img0 )

		key = cv2.waitKey(30)
		if key == ord('q') :
			break
		elif key == ord('n') :
			idx+=1
			sample = dataset[idx]
			img = sample['image']
			img0 = img[:,:,:].numpy().transpose((1,2,0))
			img0 = np.concatenate( [ img0[:,:,idx:idx+3] for idx in [0,3,6] ], axis=0)
		

def test_dataset_visualization() :
	#ann_dir = '/media/kevin/Data/DATASETS/XYS-latent/annotations'
	#img_dir = '/media/kevin/Data/DATASETS/XYS-latent/images'
	dataset = load_dataset_XYSM10_CXY_E(224)

	i=0
	continuer = True
	screen_size = [0.20,0.20]
	while continuer :
		sample = dataset.generateVisualization(idx=0+i,screen_size=screen_size)

		cv2.imshow('image', sample['image'] )
		cv2.imshow('screen', sample['visualization'] )
		
		while True :
			key = cv2.waitKey()
			if key == ord('n'):
				i+=1
				break
			if key == ord('q'):
				continuer = False
				break


def load_dataset_XYS(img_dim=224,stacking=False) :
	#ann_dir = '/media/kevin/Data/DATASETS/XYS-latent/annotations'
	#img_dir = '/media/kevin/Data/DATASETS/XYS-latent/images'
	#ann_dir = '/home/kevin/DATASETS/dataset-XYS-latent/annotations'
	#img_dir = '/home/kevin/DATASETS/dataset-XYS-latent/images'
	ann_dir = './dataset-XYS-latent/annotations'
	img_dir = './dataset-XYS-latent/images'
	width = img_dim
	height = img_dim
	transform = Transform #TransformPlus

	datasets = DatasetGazeRecognition(img_dir=img_dir,ann_dir=ann_dir,width=width,height=height,transform=transform, stacking=stacking, divide2=True)
	
	return datasets


def load_dataset_XYSM10(img_dim=224,stacking=False) :
	#ann_dir = './dataset-XYSM10-latent/annotations'
	#ann_dir = './dataset-XYSM10-latent/fixed_annotations'
	ann_dir = './dataset-XYSM10-latent/fixed_annotations_v2'
	img_dir = './dataset-XYSM10-latent/images'
	width = img_dim
	height = img_dim
	transform = Transform #TransformPlus

	datasets = DatasetGazeRecognition(img_dir=img_dir,ann_dir=ann_dir,width=width,height=height,transform=transform, stacking=stacking, divide2=False)
	
	return datasets

def load_dataset_XYSM10_CXY(img_dim=224,stacking=False) :
	ann_dir = './dataset-XYSM10-CXY-latent/annotations'
	img_dir = './dataset-XYSM10-CXY-latent/images'
	width = img_dim
	height = img_dim
	transform = Transform #TransformPlus

	datasets = DatasetGazeRecognition(img_dir=img_dir,ann_dir=ann_dir,width=width,height=height,transform=transform, stacking=stacking, divide2=True)
	
	return datasets

def load_dataset_XYSM10_CXY_2(img_dim=224,stacking=False) :
	ann_dir = './dataset-XYSM10-CXY-2-latent/annotations'
	img_dir = './dataset-XYSM10-CXY-2-latent/images'
	width = img_dim
	height = img_dim
	transform = Transform #TransformPlus

	datasets = DatasetGazeRecognition(img_dir=img_dir,ann_dir=ann_dir,width=width,height=height,transform=transform, stacking=stacking, divide2=False)
	
	return datasets

def load_dataset_XYSM10_CXY_E(img_dim=224,stacking=False) :
	ann_dir = './dataset-XYSM10-CXY-E-latent/annotations'
	img_dir = './dataset-XYSM10-CXY-E-latent/images'
	width = img_dim
	height = img_dim
	transform = Transform #TransformPlus

	datasets = DatasetGazeRecognition(img_dir=img_dir,ann_dir=ann_dir,width=width,height=height,transform=transform, stacking=stacking, divide2=False)
	
	return datasets


def load_dataset_XYSM2_C3D_EF(img_dim=224,stacking=False) :
	ann_dir = './dataset-XYSM2-C3D-EF-latent/annotations'
	img_dir = './dataset-XYSM2-C3D-EF-latent/images'
	width = img_dim
	height = img_dim
	transform = Transform #TransformPlus

	datasets = DatasetGazeRecognition(img_dir=img_dir,ann_dir=ann_dir,width=width,height=height,transform=transform, stacking=stacking, divide2=False)
	
	return datasets

def load_dataset_XYSM891215_H3D_C6D_EF(img_dim=224,stacking=False) :
	ann_dir = './dataset-XYSM891215-H3D-C6D-EF-latent/annotations'
	img_dir = './dataset-XYSM891215-H3D-C6D-EF-latent/images'
	width = img_dim
	height = img_dim
	transform = Transform #TransformPlus

	datasets = DatasetGazeRecognition(img_dir=img_dir,ann_dir=ann_dir,width=width,height=height,transform=transform, stacking=stacking, divide2=False)
	
	return datasets

def load_dataset_XYSM17182122_H3D_C6D_EF(img_dim=224,stacking=False,randomcropping=False) :
	ann_dir = './dataset-XYSM17182122-H3D-C6D-EF-latent/annotations'
	img_dir = './dataset-XYSM17182122-H3D-C6D-EF-latent/images'
	width = img_dim
	height = img_dim
	transform = Transform #TransformPlus

	datasets = DatasetGazeRecognition(img_dir=img_dir,ann_dir=ann_dir,width=width,height=height,transform=transform, stacking=stacking, divide2=False,randomcropping=randomcropping)
	
	return datasets

def load_dataset_XYSM1_H3D_C6D_EFG(img_dim=224,stacking=False,randomcropping=False) :
	ann_dir = './dataset-XYSM1-H3D-C6D-EFG-latent/annotations'
	img_dir = './dataset-XYSM1-H3D-C6D-EFG-latent/images'
	width = img_dim
	height = img_dim
	transform = Transform #TransformPlus

	datasets = DatasetGazeRecognition(img_dir=img_dir,ann_dir=ann_dir,width=width,height=height,transform=transform, stacking=stacking, divide2=False,randomcropping=randomcropping)
	
	return datasets

def generateIDX(dataset) :
	from math import floor
	nbrel = len(dataset.parsedAnnotations)
	gazex = [ round(dataset.parsedAnnotations[i]['data']['gaze']['x'], 3) for i in range(nbrel)  ]
	setgx = set(gazex)
	idx_gaze_x = [ [ idx for idx in range(nbrel) if gazex[idx] == gx] for gx in setgx]

	gazey = [  dataset.parsedAnnotations[i]['data']['gaze']['y'] for i in range(nbrel)  ]
	setgy = set(gazey)
	#print( len(setgy) )
	'''
	prec = 1e2
	gazeyf = [ floor( dataset.parsedAnnotations[i]['data']['gaze']['y']*prec)/prec for i in range(nbrel)  ]
	'''
	nbrval = 10
	limit = 0.349
	step = limit/nbrval
	ceil_vals = []
	val = 0.0
	for i in range(nbrval+1) :
		val += step
		ceil_vals.append( val)
	#print(ceil_vals)
	#print(len(ceil_vals))

	idx_gaze_y = list()
	for i in range(nbrval+1) :
		idx_gaze_y.append( list() )
	
	for i in range(len(gazey) ) :
		idx_ceil = 0 
		while ceil_vals[idx_ceil] <= gazey[i] :
			idx_ceil += 1
		idx_gaze_y[idx_ceil].append( i)

	'''
	print(idx_gaze_y[0])
	for i in range(nbrval) :
		print( len(idx_gaze_y[i]) ) 	
	'''
	'''
	for i in idx_gaze_y[0] :
		print( ' idx: {}  ::  {} >= {}'.format( i, ceil_vals[0], gazey[ i ]) )	
	'''

	headd = [ dataset.parsedAnnotations[i]['data']['head']['head_camera_distance'] for i in range(nbrel)  ]
	sethdd = set(headd)
	#print( len(sethdd) )
	#print(sethdd)
	idx_head_distance = [ [ idx for idx in range(nbrel) if headd[idx] == hdd] for hdd in sethdd]

	return idx_gaze_x, idx_gaze_y[0:10], idx_head_distance


def generateClassifier(input_dim=10,output_dim=3) :
	return LinearClassifier(input_dim=input_dim,output_dim=output_dim)


def test() :
	dataset = load_dataset_XYS(img_dim=128)
	idxgx, idxgy, idxhead = generateIDX(dataset)

	print( len(idxgx) )
	print( len(idxgy) )
	print( len(idxhead) )


if __name__ == '__main__' :
	#test_dataset()
	#test_dataset_visualization()
	test_error_visualization()
	#test_stacking()
	#test()
