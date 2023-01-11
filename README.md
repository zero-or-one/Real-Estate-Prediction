# Lifelong Property Price Prediction
Implementation of [LUCE paper](https://arxiv.org/abs/2008.05880)



### Environment
``` 
conda create -n $ENV_NAME$ python=3.5.2
conda activate $ENV_NAME$

# CUDA 11.3
pip install torch==1.5.1+cu113 --extra-index-url https://download.pytorch.org/whl/cu113 
# Or, CUDA 10.2 
pip install torch==1.5.1+cu102 --extra-index-url https://download.pytorch.org/whl/cu102 
pip install -r requirements.txt
```

### Preprocess
Create adjacency matrix and one hot encoding
```
python preprocess.py
```

### Training the model
Specify the parameters in required class in config.py
```
# create adjacency matrix and one hot encoding
python preprocess.py

# train lstm model independently
python train_lstm.py

# train gcn model independently
python train.py --config $gcn_config

# train prelifelong model
python train_prelifelong.py
```

### Things to improve
Here are the things that will be good to improve.
* Make the script to train the model end-to-end
* Creation of adjacency matrix is of O(n^2) complexity. Optimization will save a lot of time 
* Keep adjacecny matrices in scipy.sparse form as it takes less space


### Reference
* Official Implementation: https://github.com/RingBDStack/LUCE

