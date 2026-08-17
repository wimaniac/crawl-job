import os
import logging
from pathlib import Path

from llama_index.core import (
    VectorStoreIndex,
    SimpleDirectoryReader,
    StorageContext,
    load_index_from_storage,
)
from llama_index.core.node_parser import SentenceSplitter

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


# --- Đường dẫn cấu hình ---
# Thư mục gốc của dự án
PROJECT_ROOT = Path(__file__).parent.parent.parent
CV_DIR = PROJECT_ROOT / "cv_data"
PERSIST_DIR = PROJECT_ROOT / "storage" / "cv_index"
# ===========================

def get_cv_index(force_reindex: bool = False) -> VectorStoreIndex:
    """
    Xây dựng hoặc tải một VectorStoreIndex từ file CV (PDF).

    Hàm này thực hiện các công việc sau:
    1. Kiểm tra xem có file PDF nào trong thư mục `cv_data` không.
    2. Nếu `force_reindex` là True hoặc không tìm thấy index đã lưu, nó sẽ tạo index mới.
    3. Kiểm tra ngày sửa đổi của file CV so với thư mục index. Nếu CV mới hơn,
       nó sẽ tự động tạo lại index.
    4. Nếu có một index hợp lệ, nó sẽ tải index đó từ thư mục `storage/cv_index`.
    5. Lưu index mới được tạo vào `storage/cv_index` để sử dụng lại.

    Args:
        force_reindex (bool): Nếu True, bắt buộc tạo lại index ngay cả khi đã có.

    Returns:
        VectorStoreIndex: Đối tượng index của LlamaIndex.
        
    Raises:
        FileNotFoundError: Nếu không tìm thấy file PDF nào trong thư mục CV_DIR.
    """
    
    # 1. Tìm file CV
    try:
        cv_file = next(CV_DIR.glob("*.pdf"))
    except StopIteration:
        logging.error(f"Không tìm thấy file CV (PDF) nào trong thư mục: {CV_DIR}")
        raise FileNotFoundError(f"Vui lòng đặt file CV (định dạng .pdf) của bạn vào thư mục: {CV_DIR}")

    # 2. Kiểm tra điều kiện để tạo lại index
    should_reindex = True
    if not force_reindex and PERSIST_DIR.exists():
        # Lấy thời gian sửa đổi cuối cùng của thư mục index
        index_mtime = PERSIST_DIR.stat().st_mtime
        # Lấy thời gian sửa đổi của file CV
        cv_mtime = cv_file.stat().st_mtime
        
        if index_mtime >= cv_mtime:
            logging.info(f"CV không thay đổi. Tải index có sẵn từ '{PERSIST_DIR}'...")
            should_reindex = False

    # 3. Tạo mới hoặc tải index
    if should_reindex:
        logging.info(f"Đang tạo index mới từ file '{cv_file.name}'...")
        if PERSIST_DIR.exists():
            logging.info("Đã phát hiện CV mới hơn hoặc được yêu cầu tạo lại index. Xóa index cũ.")
            # Xóa index cũ đi, để tránh lỗi
            import shutil
            shutil.rmtree(PERSIST_DIR)

        # Tải dữ liệu từ file PDF
        reader = SimpleDirectoryReader(input_dir=CV_DIR, required_exts=[".pdf"])
        documents = reader.load_data()
        
        if not documents:
            raise Exception("Không thể đọc được nội dung từ file PDF. File có thể bị hỏng hoặc trống.")
            
        # Tách văn bản thành các chunk nhỏ hơn
        splitter = SentenceSplitter(chunk_size=1024, chunk_overlap=20)
        
        # Tạo index từ các document
        index = VectorStoreIndex.from_documents(documents, transformations=[splitter])
        
        # Lưu index vào ổ đĩa để tái sử dụng
        logging.info(f"Đang lưu index vào '{PERSIST_DIR}'...")
        index.storage_context.persist(persist_dir=PERSIST_DIR)
        logging.info("Lưu index thành công.")
        
    else: # Tải index đã có
        storage_context = StorageContext.from_defaults(persist_dir=PERSIST_DIR)
        index = load_index_from_storage(storage_context)
        logging.info("Tải index thành công.")
        
    return index

if __name__ == '__main__':
    # --- Dành cho việc chạy thử nghiệm ---
    print("Bắt đầu chạy thử nghiệm module `cv_indexer`...")
    print(f"Thư mục CV: {CV_DIR}")
    print(f"Thư mục lưu trữ Index: {PERSIST_DIR}")

    # Tạo một file PDF giả để test
    if not CV_DIR.exists():
        CV_DIR.mkdir()

    # Kiểm tra xem có file PDF nào không, nếu không thì tạo file giả
    try:
        next(CV_DIR.glob("*.pdf"))
    except StopIteration:
        print("\nKhông tìm thấy file PDF nào. Đang tạo file 'dummy_cv.pdf' để thử nghiệm...")
        # Cần thư viện `fpdf` để tạo file, nếu chưa có thì phải cài
        try:
            from fpdf import FPDF
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Arial", size=12)
            pdf.cell(200, 10, txt="Đây là CV mẫu của một Lập trình viên Python với 5 năm kinh nghiệm.", ln=True, align='C')
            pdf.multi_cell(0, 10, txt="Kỹ năng: Python, Django, FastAPI, Scrapy, LlamaIndex, PostgreSQL. Có kinh nghiệm xây dựng hệ thống ETL và các pipeline xử lý dữ liệu lớn.")
            dummy_cv_path = CV_DIR / "dummy_cv.pdf"
            pdf.output(dummy_cv_path)
            print(f"Đã tạo file '{dummy_cv_path}' thành công.")
        except ImportError:
            print("\nCẢNH BÁO: Thư viện `fpdf` chưa được cài đặt (`uv pip install fpdf`).")
            print("Không thể tạo file PDF mẫu. Vui lòng tự đặt một file PDF vào thưc mục 'cv_data' để chạy thử nghiệm.")
            exit()
        except Exception as e:
            print(f"Lỗi khi tạo file PDF mẫu: {e}")
            exit()

    print("\n--- Lần 1: Tạo index ---")
    # Lần đầu chạy sẽ tạo index mới
    cv_index = get_cv_index(force_reindex=True)
    print(f"Index ID: {cv_index.index_id}")
    print("Trạng thái: Đã tạo và lưu index mới.")

    print("\n--- Lần 2: Tải index có sẵn ---")
    # Lần thứ hai sẽ tải lại index đã có
    cv_index_loaded = get_cv_index()
    print(f"Index ID: {cv_index_loaded.index_id}")
    print("Trạng thái: Đã tải lại index từ bộ nhớ.")
    
    # So sánh để chắc chắn 2 index là một
    assert cv_index.index_id == cv_index_loaded.index_id
    print("\nKiểm tra thành công: ID của index tạo mới và index được tải là giống nhau.")

    print("\nThử nghiệm module `cv_indexer` hoàn tất!")
