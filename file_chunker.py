import pandas as pd
chunk_size = 500000 # Number of rows
for i, chunk in enumerate(pd.read_csv('complaints.csv', chunksize=chunk_size)):
    chunk.to_csv(f'complaint_data/split_file_{i}.csv', index=False)