# Gunakan base image Python
FROM python:3.9-slim

# Set direktori kerja di dalam container
WORKDIR /app

# Salin file dependencies dan install
COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt

# Salin semua file aplikasi ke dalam container
COPY . .

# Beri tahu Docker bahwa container berjalan di port 8080
EXPOSE 8080

# Jalankan aplikasi saat container dimulai
CMD ["python", "app.py"]
