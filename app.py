# ============================================================
# IMPORT LIBRARY
# ============================================================
import os
import uuid
import shutil
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from PIL import Image
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib.pagesizes import A4

# ============================================================
# PROGRESS TRACKING
# ============================================================
upload_progress = {}

def update_progress(file_uuid, percent, message):
    upload_progress[file_uuid] = {'percent': percent, 'message': message}
    print(f"  [Progress] {percent}% - {message}")

# ============================================================
# KONFIGURASI APP
# ============================================================
app = Flask(__name__)
app.config.from_object('config.Config')

db = SQLAlchemy(app)

# ============================================================
# MODEL DATABASE
# ============================================================
class ConversionRecord(db.Model):
    """Model untuk tabel riwayat konversi gambar ke PDF"""
    __tablename__ = 'conversion_record'

    id                = db.Column(db.Integer, primary_key=True)
    original_filename = db.Column(db.String(255), nullable=False)
    pdf_filename      = db.Column(db.String(255), nullable=False)
    file_size         = db.Column(db.Integer, nullable=True)   # bytes
    created_at        = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        size_kb = f'{self.file_size / 1024:.1f} KB' if self.file_size else '-'
        return {
            'id'               : self.id,
            'original_filename': self.original_filename,
            'pdf_filename'     : self.pdf_filename,
            'file_size'        : size_kb,
            'created_at'       : self.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        }

# ============================================================
# FUNGSI BANTUAN
# ============================================================
def allowed_file(filename):
    """Cek apakah file adalah gambar yang didukung"""
    return (
        '.' in filename
        and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']
    )

def convert_image_to_pdf(image_path, output_path):
    """
    Konversi file gambar menjadi PDF ukuran A4.
    Gambar di-scale proporsional agar fit di halaman dengan margin 20pt.
    """
    img = Image.open(image_path).convert('RGB')
    iw, ih  = img.size
    pw, ph  = A4                  # 595 x 842 pt
    margin  = 20

    scale = min((pw - margin * 2) / iw, (ph - margin * 2) / ih)
    fw = iw * scale
    fh = ih * scale
    fx = (pw - fw) / 2
    fy = (ph - fh) / 2

    # Simpan gambar sementara sebagai JPEG untuk reportlab
    tmp_jpg = output_path.replace('.pdf', '_tmp.jpg')
    img.save(tmp_jpg, 'JPEG', quality=92)

    c = rl_canvas.Canvas(output_path, pagesize=A4)
    c.drawImage(tmp_jpg, fx, fy, width=fw, height=fh)
    c.save()

    os.remove(tmp_jpg)

# ============================================================
# ROUTES (HALAMAN)
# ============================================================
@app.route('/progress/<file_uuid>')
def get_progress(file_uuid):
    """API untuk cek progress upload & konversi"""
    progress = upload_progress.get(file_uuid, {'percent': 0, 'message': 'Menunggu...'})
    return jsonify(progress)

@app.route('/')
def index():
    """Halaman utama - upload gambar"""
    return render_template('index.html')

@app.route('/data')
def data():
    """Halaman riwayat konversi"""
    return render_template('data.html')

# ============================================================
# ROUTES API (Termasuk Chunked Upload)
# ============================================================
@app.route('/upload', methods=['POST'])
def upload():
    """
    API untuk upload file gambar (supports chunked upload via Dropzone.js).
    Chunk dirakit, lalu gambar dikonversi ke PDF dan hasilnya disimpan ke DB.
    """
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': 'Tidak ada file yang dikirim'}), 400

    file              = request.files.get('file')
    file_uuid         = request.form.get('dzuuid')
    chunk_index       = request.form.get('dzchunkindex')
    total_chunks      = request.form.get('dztotalchunkcount')
    original_filename = request.form.get('filename', file.filename)

    if not file or file.filename == '':
        return jsonify({'success': False, 'message': 'Tidak ada file yang dipilih'}), 400

    if not allowed_file(original_filename):
        return jsonify({'success': False, 'message': 'Format file tidak didukung'}), 400

    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    # ── Chunked upload ────────────────────────────────────────
    if file_uuid and chunk_index is not None:
        chunk_folder = os.path.join(app.config['UPLOAD_FOLDER'], 'chunks', file_uuid)
        os.makedirs(chunk_folder, exist_ok=True)

        chunk_path = os.path.join(chunk_folder, f'chunk_{chunk_index}')
        file.save(chunk_path)

        # Belum semua chunk tiba → konfirmasi chunk diterima
        if int(chunk_index) < int(total_chunks) - 1:
            return jsonify({
                'success'    : True,
                'chunkIndex' : int(chunk_index),
                'totalChunks': int(total_chunks),
            })

        # Semua chunk sudah tiba → rakit file
        try:
            chunks = sorted(
                [f for f in os.listdir(chunk_folder) if f.startswith('chunk_')],
                key=lambda x: int(x.split('_')[1])
            )

            ext              = original_filename.rsplit('.', 1)[1].lower()
            unique_img_name  = f'{uuid.uuid4()}.{ext}'
            img_path         = os.path.join(app.config['UPLOAD_FOLDER'], unique_img_name)

            with open(img_path, 'wb') as outfile:
                for chunk_file in chunks:
                    with open(os.path.join(chunk_folder, chunk_file), 'rb') as infile:
                        outfile.write(infile.read())

            shutil.rmtree(chunk_folder)

            update_progress(file_uuid, 60, 'Merakit file...')
            return _process_and_save(img_path, original_filename, file_uuid)

        except Exception as e:
            return jsonify({'success': False, 'message': f'Error merakit chunk: {str(e)}'}), 500

    # ── Upload biasa (tanpa chunking) ─────────────────────────
    try:
        ext             = original_filename.rsplit('.', 1)[1].lower()
        unique_img_name = f'{uuid.uuid4()}.{ext}'
        img_path        = os.path.join(app.config['UPLOAD_FOLDER'], unique_img_name)
        file.save(img_path)

        return _process_and_save(img_path, original_filename)

    except Exception as e:
        return jsonify({'success': False, 'message': f'Error memproses file: {str(e)}'}), 500


def _process_and_save(img_path, original_filename, file_uuid=None):
    """Helper: konversi gambar ke PDF, simpan ke DB, return JSON response."""
    def prog(percent, message):
        if file_uuid:
            update_progress(file_uuid, percent, message)

    prog(65, 'Membuka file gambar...')
    file_size    = os.path.getsize(img_path)
    pdf_filename = os.path.splitext(os.path.basename(img_path))[0] + '.pdf'
    pdf_path     = os.path.join(app.config['UPLOAD_FOLDER'], pdf_filename)

    prog(75, 'Mengonversi gambar ke PDF...')
    convert_image_to_pdf(img_path, pdf_path)

    prog(90, 'Menyimpan ke database...')
    record = ConversionRecord(
        original_filename=original_filename,
        pdf_filename=pdf_filename,
        file_size=file_size,
    )
    db.session.add(record)
    db.session.commit()

    prog(100, 'Selesai!')
    if file_uuid:
        upload_progress.pop(file_uuid, None)

    return jsonify({
        'success'      : True,
        'message'      : 'Konversi berhasil',
        'record_id'    : record.id,
        'filename'     : original_filename,
        'pdf_filename' : pdf_filename,
    })


@app.route('/api/records', methods=['GET'])
def api_records():
    """API untuk ambil semua riwayat konversi"""
    records = ConversionRecord.query.order_by(ConversionRecord.created_at.desc()).all()
    return jsonify([r.to_dict() for r in records])


@app.route('/download/<int:record_id>')
def download_pdf(record_id):
    """Download PDF hasil konversi"""
    record   = ConversionRecord.query.get_or_404(record_id)
    pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], record.pdf_filename)

    if not os.path.exists(pdf_path):
        return jsonify({'error': 'File tidak ditemukan'}), 404

    download_name = os.path.splitext(record.original_filename)[0] + '.pdf'
    return send_file(pdf_path, as_attachment=True, download_name=download_name)


@app.route('/delete/<int:record_id>', methods=['POST'])
def delete_record(record_id):
    """Hapus record dan file terkait"""
    record = ConversionRecord.query.get_or_404(record_id)

    # Hapus file gambar & PDF dari disk
    for filename in (record.pdf_filename,):
        fpath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        if os.path.exists(fpath):
            os.remove(fpath)

    db.session.delete(record)
    db.session.commit()

    # Reset sequence ID agar tetap rapi
    remaining = ConversionRecord.query.order_by(ConversionRecord.id).all()
    if remaining:
        for idx, rec in enumerate(remaining, start=1):
            rec.id = idx
        db.session.commit()
        db.session.execute(text(
            "SELECT setval(pg_get_serial_sequence('conversion_record', 'id'), "
            "(SELECT MAX(id) FROM conversion_record))"
        ))
    else:
        db.session.execute(text(
            "SELECT setval(pg_get_serial_sequence('conversion_record', 'id'), 1)"
        ))
    db.session.commit()

    return redirect(url_for('data'))


# ============================================================
# MAIN
# ============================================================
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, host='0.0.0.0', port=5000)