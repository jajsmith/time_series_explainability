from TSX.utils import load_data, load_simulated_data, load_ghg_data
from TSX.experiments import Baseline, EncoderPredictor, FeatureGeneratorExplainer, BaselineExplainer

import os
import sys
import json
import argparse
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

intervention_list = ['vent', 'vaso', 'adenosine', 'dobutamine', 'dopamine', 'epinephrine', 'isuprel', 'milrinone',
                     'norepinephrine', 'phenylephrine', 'vasopressin', 'colloid_bolus', 'crystalloid_bolus', 'nivdurations']
feature_map_mimic = ['ANION GAP', 'ALBUMIN', 'BICARBONATE', 'BILIRUBIN', 'CREATININE', 'CHLORIDE', 'GLUCOSE',
                     'HEMATOCRIT', 'HEMOGLOBIN', 'LACTATE', 'MAGNESIUM', 'PHOSPHATE', 'PLATELET', 'POTASSIUM', 'PTT',
                     'INR', 'PT', 'SODIUM', 'BUN', 'WBC', 'HeartRate', 'SysBP', 'DiasBP', 'MeanBP', 'RespRate', 'SpO2',
                     'Glucose', 'Temp']

MIMIC_TEST_SAMPLES = list(range(70))
SIMULATION_SAMPLES = [7, 23, 78, 95, 120, 157, 51, 11, 101, 48]
samples_to_analyze = {'mimic':MIMIC_TEST_SAMPLES, 'simulation':SIMULATION_SAMPLES, 'ghg':[], 'simulation_spike':[]}


def main(experiment, train, data, generator_type, predictor_model, all_samples,cv=0):
    print('********** Experiment with the %s data **********' %(experiment))
    with open('config.json') as config_file:
        configs = json.load(config_file)[data][experiment]


    ## Load the data
    if data == 'mimic':
        p_data, train_loader, valid_loader, test_loader = load_data(batch_size=configs['batch_size'],
                                                                    path='./data',cv=cv)
        feature_size = p_data.feature_size
    elif data == 'ghg':
        p_data, train_loader, valid_loader, test_loader = load_ghg_data(configs['batch_size'],cv=cv)
        feature_size = p_data.feature_size
    elif data == 'simulation_spike':
        p_data, train_loader, valid_loader, test_loader = load_simulated_data(batch_size=configs['batch_size'],
                                                                              path='./data/simulated_spike_data',
                                                                              data_type='spike',cv=cv)
        feature_size = p_data.shape[1]

    elif data == 'simulation':
        percentage = 100.
        p_data, train_loader, valid_loader, test_loader = load_simulated_data(batch_size=configs['batch_size'],
                                                                              path='./data/simulated_data',
                                                                              percentage=percentage/100,cv=cv)
        feature_size = p_data.shape[1]


    ## Create the experiment class
    if experiment == 'baseline':
        exp = Baseline(train_loader, valid_loader, test_loader, p_data.feature_size)
    elif experiment == 'risk_predictor':
        exp = EncoderPredictor(train_loader, valid_loader, test_loader, feature_size, configs['encoding_size'],
                               rnn_type=configs['rnn_type'], data=data, model=predictor_model)
    elif experiment == 'feature_generator_explainer':
        exp = FeatureGeneratorExplainer(train_loader, valid_loader, test_loader, feature_size, patient_data=p_data,
                                        predictor_model=predictor_model,generator_hidden_size=configs['encoding_size'],
                                        prediction_size=1, historical=(configs['historical']==1),
                                        generator_type=generator_type, data=data, experiment=experiment+'_'+generator_type)
    elif experiment == 'lime_explainer':
        exp = BaselineExplainer(train_loader, valid_loader, test_loader, feature_size, data_class=p_data, data=data, baseline_method='lime')

    if all_samples:
        print('Experiment on all test data')
        print('Number of test samples: ', len(exp.test_loader.dataset))
        exp.run(train=False, n_epochs=configs['n_epochs'], samples_to_analyze=list(range(359,len(exp.test_loader.dataset))),
                plot=False, cv=cv)
    else:
        exp.run(train=train, n_epochs=configs['n_epochs'], samples_to_analyze=samples_to_analyze[data])


    # span = []
    # device = 'cuda' if torch.cuda.is_available() else 'cpu'
    # # # import matplotlib.pyplot as plt
    # testset = list(exp.test_loader.dataset)
    # # # signals = torch.stack(([x[0] for x in testset]))
    # # # plt.plot(np.array(signals[4126,2,:]))
    # # # plt.show()
    # for i,(signal,label) in enumerate(testset):
    #    exp.risk_predictor.load_state_dict(torch.load('./ckpt/mimic/risk_predictor_RNN.pt'))
    #    exp.risk_predictor.to(device)
    #    exp.risk_predictor.eval()
    #    risk=[]
    #    for t in range(1,48):
    #        risk.append(exp.risk_predictor(signal[:, 0:t].view(1, signal.shape[0], t).to(device)).item())
    #    span.append((i,max(risk) - min(risk)))
    # span.sort(key= lambda pair:pair[1], reverse=True)
    # print([x[0] for x in span[0:300]])
    # print([x[1] for x in span[0:300]])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Train an ICU mortality prediction model')
    parser.add_argument('--model', type=str, default='feature_generator_explainer', help='Prediction model')
    parser.add_argument('--data', type=str, default='mimic')
    parser.add_argument('--generator', type=str, default='joint_RNN_generator')
    parser.add_argument('--predictor', type=str, default='RNN')
    parser.add_argument('--train', action='store_true')
    parser.add_argument('--all_samples', action='store_true')
    parser.add_argument('--cv', type=int, default=0)
    args = parser.parse_args()
    main(args.model, train=args.train, data=args.data, generator_type=args.generator, predictor_model=args.predictor,
         all_samples=args.all_samples,cv=args.cv)
