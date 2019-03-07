import pickle
import numpy as np
import random 
import os
import torch
import torch.utils.data as utils
from torch.utils.data import DataLoader
from sklearn import preprocessing
from sklearn.metrics import f1_score, recall_score, precision_score, roc_curve 
from sklearn.metrics import auc as auc_score
from models import EncoderRNN, DecoderRNN, Encoder, Decoder,RiskPredictor, LR

len_of_stay = 48

class PatientData():
	"""Dataset of patient vitals, demographics and lab results
	Args:
		root: Root directory of dataset the pickled dataset
		train_ratio: train/test ratio
		shuffle: Shuffle dataset before separting train/test
	"""
	def __init__(self, root, train_ratio=0.8, shuffle=True, random_seed='1234', transform="normalize"):
		self.data_dir = os.path.join(root,'patient_vital_preprocessed.pkl')
		self.train_ratio = train_ratio  
		self.random_seed = random.seed(random_seed) 

		if not os.path.exists(self.data_dir):
			raise RuntimeError('Dataset not found')
		with open(self.data_dir ,'rb') as f:
			self.data = pickle.load(f)	
		if shuffle:
			random.shuffle(self.data)
		self.feature_size = len(self.data[0][0])
		self.n_train = int(len(self.data)*self.train_ratio)
		self.n_test = len(self.data)-self.n_train
		self.train_data = np.array( [x for (x,y,z) in self.data[0:self.n_train] ]  )
		self.test_data = np.array( [ x for (x,y,z) in self.data[self.n_train:]]  )
		self.train_label = np.array( [y for (x,y,z) in self.data[0:self.n_train] ]  )
		self.test_label = np.array( [ y for (x,y,z) in self.data[self.n_train:]]  )
		self.train_missing = np.array( [np.mean(z) for (x,y,z) in self.data[0:self.n_train] ]  )
		self.test_missing = np.array( [ np.mean(z) for (x,y,z) in self.data[self.n_train:]]  )
		if transform=="normalize":
			self.normalize()


	def __getitem__(self, index):
		signals, target = self.data[index]
		return signals, target

	def __len__(self):
		return len(self.data)

	def normalize(self):
		''' Calculate the mean and std of each feature from the training set
		'''
		d = [x.T for x in self.train_data]
		d = np.stack(d, axis=0)		
		self.feature_max = np.tile(np.max(d.reshape(-1,self.feature_size), axis=0) , (48,1)).T
		self.feature_min = np.tile(np.min(d.reshape(-1,self.feature_size), axis=0) , (48,1)).T
		self.feature_means= np.tile(np.mean(d.reshape(-1,self.feature_size), axis=0) , (len_of_stay,1)).T
		self.feature_std = np.tile(np.std(d.reshape(-1,self.feature_size), axis=0) , (len_of_stay,1)).T
		#self.train_data = np.array([ np.where(self.feature_std==0,(x-self.feature_means),(x-self.feature_means)/self.feature_std )    for x in self.train_data])
		#self.test_data = np.array([ np.where(self.feature_std==0,(x-self.feature_means),(x-self.feature_means)/self.feature_std )    for x in self.test_data])
		self.train_data = np.array([ np.where(self.feature_min==self.feature_max,(x-self.feature_min),(x-self.feature_min)/(self.feature_max-self.feature_min) )    for x in self.train_data])
		self.test_data = np.array([ np.where(self.feature_min==self.feature_max,(x-self.feature_min),(x-self.feature_min)/(self.feature_max-self.feature_min) )    for x in self.test_data])


def evaluate(labels, predicted_label, predicted_probability):
	fpr, tpr, thresholds = roc_curve(np.array(labels.cpu()), np.array(predicted_probability.view(len(labels),-1).detach().cpu().numpy()), pos_label=1)
	auc = auc_score(fpr, tpr)
	recall = recall_score(np.array(labels.cpu()),np.array(predicted_label.cpu()))
	precision = precision_score(np.array(labels.cpu()),np.array(predicted_label.cpu()))
	correct_label = torch.eq(labels,predicted_label).sum()
	return auc, recall, precision, correct_label



def test_model(test_loader, model, device, criteria=torch.nn.BCELoss(), verbose=True):
	correct_label = 0	
	recall_test, precision_test, auc_test = 0, 0, 0
	count=0
	
	model.eval()
	for i, (x,y) in enumerate(test_loader):
		x,y = torch.Tensor(x.float()).to(device), torch.Tensor(y.float()).to(device)
		#out = model(x.mean(dim=2).reshape((len(y),-1)))
		out = model(x.permute(2,0,1))
		prediction = (out>0.5).view(len(y),).float()
		auc, recall, precision, correct = evaluate(y, prediction, out)
		correct_label += correct
		auc_test =+ auc
		recall_test =+ recall
		precision_test =+ precision
		count =+ 1
		loss =+ criteria(out.view(len(y),), y).item()
	if verbose:
		print('Test ===>loss: ', loss, ' Accuracy: %.2f percent'%(100*correct_label/(count*len(test_loader))), ' AUC: %.2f'%(auc_test/count))


def train_model(train_loader, model, device, optimizer, loss_criterion=torch.nn.BCELoss(), verbose=True):
	model.train()
	recall_train, precision_train, auc_train, correct_label, epoch_loss = 0, 0, 0, 0, 0
	count=0
	for i, (signals,labels) in enumerate(train_loader):
		optimizer.zero_grad()
		signals,labels = torch.Tensor(signals.float()).to(device), torch.Tensor(labels.float()).to(device)
		loss_criterion = torch.nn.BCELoss(weight=8*labels+1)
		#risks = model(signals.mean(dim=2).reshape((len(labels),-1)))
		risks = model(signals.permute(2,0,1))
		predicted_label = (risks>0.5).view(len(labels),).float()

		auc, recall, precision, correct = evaluate(labels, predicted_label, risks)
		correct_label += correct
		auc_train =+ auc
		recall_train =+ recall
		precision_train =+ precision
		count =+ 1

		loss = loss_criterion(risks.view(len(labels),), labels)
		epoch_loss =+ loss.item()
		loss.backward()
		optimizer.step()
	return recall_train/count, precision_train/count, auc_train/count, correct_label, epoch_loss 



def main(experiment='encoder'):

	print('********** Experiment with %s model **********'%(experiment))

	encoding_size = 100
	batch_size=100
	device = 'cuda' if torch.cuda.is_available() else 'cpu'

	p_data = PatientData('../data_generator/data')
	train_dataset = utils.TensorDataset(torch.Tensor(p_data.train_data[0:int(0.8*p_data.n_train),:,:]), torch.Tensor(p_data.train_label[0:int(0.8*p_data.n_train)]) )
	valid_dataset = utils.TensorDataset(torch.Tensor(p_data.train_data[int(0.8*p_data.n_train): ,:,:]), torch.Tensor(p_data.train_label[int(0.8*p_data.n_train):]) )
	test_dataset = utils.TensorDataset(torch.Tensor(p_data.test_data), torch.Tensor(p_data.test_label) )
	train_loader = DataLoader(train_dataset, batch_size=batch_size)
	valid_loader = DataLoader(valid_dataset, batch_size=p_data.n_train-int(0.8*p_data.n_train))
	test_loader = DataLoader(test_dataset, batch_size=p_data.n_test)
	print('Train set: ', np.count_nonzero(p_data.train_label[0:int(0.8*p_data.n_train)]) , 'patient who died from total of ', int(0.8*p_data.n_train) , '(Average missing in train+valid: %.2f)'%(np.mean(p_data.train_missing)))
	print('Valid set: ', np.count_nonzero(p_data.train_label[int(0.8*p_data.n_train):]) , 'patient who died from total of ', len(p_data.train_label[int(0.8*p_data.n_train):]) )
	print('Test set: ', np.count_nonzero(p_data.test_label) , 'patient who died from total of ', len(p_data.test_label) , '(Average missing in test: %.2f)'%(np.mean(p_data.test_missing)) )

	if experiment=='LR':
		model = LR(feature_size=p_data.feature_size)
	elif experiment=='encoder':
		model = EncoderRNN(feature_size=p_data.feature_size , hidden_size=encoding_size, rnn='GRU')
	elif experiment=='risk_predictor':
		state_encoder = EncoderRNN(feature_size=p_data.feature_size , hidden_size=encoding_size, rnn='GRU')
		risk_predictor = RiskPredictor(encoding_size=encoding_size , demographic_size=4)
		model = torch.nn.Sequential(state_encoder,risk_predictor)

	model = model.to(device)
	parameters = model.parameters()
	#optimizer = torch.optim.Adam(parameters)
	optimizer = torch.optim.SGD(parameters, lr=0.0001, momentum=0.9, weight_decay=1e-4)

	for epoch in range(101):
		lr = 0.01 * (0.1 ** (epoch // 30))
		for param_group in optimizer.param_groups:
			param_group['lr'] = lr
		recall_train, precision_train, auc_train, correct_label, epoch_loss = train_model(train_loader, model, device, optimizer)
		if epoch%10==0:
			print('\nEpoch %d'%(epoch))
			print('Training ===>loss: ', epoch_loss, ' Accuracy: %.2f percent'%(100*correct_label/(0.800*p_data.n_train)), ' AUC: %.2f'%(auc_train))
			test_model(valid_loader, model, device)
		
	print('Final performance on held out test set:')		
	test_model(test_loader, model, device)

if __name__=='__main__':
	main()








