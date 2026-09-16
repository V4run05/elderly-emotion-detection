import os
import pickle
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, accuracy_score
import joblib

# Target sampling rate for all signals to align them
TARGET_SR = 32
WINDOW_SEC = 60
OVERLAP_SEC = 30

# WESAD Labels:
# 0 = not defined / transient, 1 = baseline, 2 = stress, 3 = amusement, 4 = meditation
# We only care about 1, 2, 3, 4.
# Map to our 4-class taxonomy: Anger, Happiness, Neutral, Sadness
LABEL_MAP = {
    1: "Neutral",
    2: "Sadness", # Mapping stress to a negative emotion in our taxonomy
    3: "Happiness",
    4: "Neutral"  # Meditation is close to neutral
}

def resample_signal(signal, orig_sr, target_sr):
    if orig_sr == target_sr:
        return signal
    
    duration = len(signal) / orig_sr
    num_target_samples = int(duration * target_sr)
    
    # Simple linear interpolation
    x_orig = np.linspace(0, duration, len(signal))
    x_target = np.linspace(0, duration, num_target_samples)
    
    if len(signal.shape) > 1:
        resampled = np.zeros((num_target_samples, signal.shape[1]))
        for i in range(signal.shape[1]):
            resampled[:, i] = np.interp(x_target, x_orig, signal[:, i])
        return resampled
    else:
        return np.interp(x_target, x_orig, signal)

def extract_features(window_data):
    # window_data shape: (N_samples, 5) -> ACC_x, ACC_y, ACC_z, BVP, EDA
    features = []
    
    for i in range(5):
        channel_data = window_data[:, i]
        features.extend([
            np.mean(channel_data),
            np.std(channel_data),
            np.min(channel_data),
            np.max(channel_data),
            # peak-to-peak
            np.ptp(channel_data)
        ])
    return features

def load_subject_data(subject_path):
    with open(subject_path, 'rb') as f:
        data = pickle.load(f, encoding='latin1')
    
    wrist = data['signal']['wrist']
    acc = wrist['ACC'] # 32 Hz
    bvp = wrist['BVP'] # 64 Hz
    eda = wrist['EDA'] # 4 Hz
    
    label = data['label'] # 700 Hz
    
    # Resample everything to TARGET_SR (32 Hz)
    bvp_resampled = resample_signal(bvp, 64, TARGET_SR)
    eda_resampled = resample_signal(eda, 4, TARGET_SR)
    label_resampled = resample_signal(label, 700, TARGET_SR)
    label_resampled = np.round(label_resampled).astype(int)
    
    # Truncate to min length to align
    min_len = min(len(acc), len(bvp_resampled), len(eda_resampled), len(label_resampled))
    
    acc = acc[:min_len]
    bvp_resampled = bvp_resampled[:min_len]
    eda_resampled = eda_resampled[:min_len]
    label_resampled = label_resampled[:min_len]
    
    # Combine signals: ACC(3), BVP(1), EDA(1) -> 5 channels
    signals = np.hstack((acc, bvp_resampled, eda_resampled))
    
    return signals, label_resampled

def process_subject(subject_path):
    print(f"Processing {subject_path}...")
    signals, labels = load_subject_data(subject_path)
    
    window_samples = WINDOW_SEC * TARGET_SR
    step_samples = (WINDOW_SEC - OVERLAP_SEC) * TARGET_SR
    
    X = []
    y = []
    
    for start in range(0, len(signals) - window_samples + 1, step_samples):
        end = start + window_samples
        window_signals = signals[start:end]
        window_labels = labels[start:end]
        
        # Determine the majority label in the window
        values, counts = np.unique(window_labels, return_counts=True)
        majority_label = values[np.argmax(counts)]
        
        # Only use windows that have a valid mapped label
        if majority_label in LABEL_MAP:
            features = extract_features(window_signals)
            X.append(features)
            y.append(LABEL_MAP[majority_label])
            
    return np.array(X), np.array(y)

def main():
    wesad_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "WESAD")
    subjects = [d for d in os.listdir(wesad_dir) if d.startswith("S") and os.path.isdir(os.path.join(wesad_dir, d))]
    
    X_all, y_all, groups = [], [], []
    
    for subject in subjects:
        subject_pkl = os.path.join(wesad_dir, subject, f"{subject}.pkl")
        if not os.path.exists(subject_pkl):
            continue
            
        X_sub, y_sub = process_subject(subject_pkl)
        if len(X_sub) > 0:
            X_all.append(X_sub)
            y_all.append(y_sub)
            groups.extend([subject] * len(X_sub))
            
    X_all = np.vstack(X_all)
    y_all = np.concatenate(y_all)
    groups = np.array(groups)
    
    print(f"Total samples: {len(X_all)}")
    
    # Train Random Forest
    rf = RandomForestClassifier(n_estimators=100, random_state=42, n_jobs=-1, class_weight='balanced')
    rf.fit(X_all, y_all)
    
    # Save the model
    app_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app")
    physio_dir = os.path.join(app_dir, "physio_emotion")
    os.makedirs(physio_dir, exist_ok=True)
    
    # Create empty __init__.py
    open(os.path.join(physio_dir, "__init__.py"), "w").close()
    
    model_path = os.path.join(physio_dir, "rf_model.pkl")
    joblib.dump(rf, model_path)
    print(f"Saved model to {model_path}")
    
    # Basic evaluate on train set to check
    preds = rf.predict(X_all)
    print("Train set accuracy:", accuracy_score(y_all, preds))
    print(classification_report(y_all, preds))

if __name__ == "__main__":
    main()
