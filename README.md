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

### Train model

### Reference
* Official Implementation: https://github.com/RingBDStack/LUCE
