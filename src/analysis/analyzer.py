import logging
import json
from llama_index.core import VectorStoreIndex, get_settings
from llama_index.core.prompts import PromptTemplate
from llama_index.llms.ollama import Ollama
from .cv_indexer import get_cv_index

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Cấu hình mô hình và prompt ---
LLM_MODEL = "phi3:mini" # Sử dụng phi3:mini, một model nhỏ gọn và hiệu quả
JSON_ANALYSIS_PROMPT = PromptTemplate("""
Dựa trên CV được cung cấp, hãy phân tích Mô tả công việc (Job Description) sau đây.
Đưa ra một câu trả lời dưới dạng một JSON object DUY NHẤT, không có bất kỳ giải thích hay văn bản nào khác.
JSON object phải có cấu trúc như sau:
{{
    "match_score": <một số nguyên từ 0 đến 100, thể hiện mức độ phù hợp của CV với công việc>,
    "ai_analysis": "<một chuỗi tóm tắt ngắn gọn (2-3 câu) về lý do phù hợp hoặc không phù hợp, nhấn mạnh vào các kỹ năng hoặc kinh nghiệm chính>"
}}

Đây là các thông tin liên quan từ CV của ứng viên:
---------------------
{context_str}
---------------------

Đây là Mô tả công việc cần phân tích:
---------------------
{query_str}
---------------------

Hãy tạo JSON object:
""")

def setup_llm_and_query_engine(cv_index: VectorStoreIndex):
    """
    Cấu hình LLM và tạo một query engine từ CV index.
    """
    # Cấu hình để LlamaIndex sử dụng model Ollama local
    # Model 'phi3:mini' được khuyến nghị vì nhỏ gọn và hiệu quả cho tác vụ này
    settings_llm = Ollama(model=LLM_MODEL, request_timeout=120.0)
    
    # Thiết lập LLM cho toàn bộ LlamaIndex context
    # (Mặc dù chúng ta sẽ truyền nó trực tiếp vào query engine)
    get_settings().llm = settings_llm

    # Tạo một query engine với prompt template đã tùy chỉnh
    # 'response_mode="compact"' giúp model trả lời ngắn gọn hơn
    query_engine = cv_index.as_query_engine(
        text_qa_template=JSON_ANALYSIS_PROMPT,
        response_mode="compact",
        llm=settings_llm, 
    )
    return query_engine

def analyze_job_description(query_engine, job_description: str) -> dict | None:
    """
    Sử dụng query engine để phân tích một mô tả công việc.
    
    Args:
        query_engine: Query engine đã được cấu hình.
        job_description: Chuỗi mô tả công việc cần phân tích.

    Returns:
        Một dictionary chứa 'match_score' và 'ai_analysis', hoặc None nếu có lỗi.
    """
    logging.info("Bắt đầu phân tích mô tả công việc...")
    
    try:
        response = query_engine.query(job_description)
        response_text = str(response).strip()
        
        # Đôi khi model vẫn trả về markdown ```json ... ```, cần làm sạch
        if response_text.startswith("```json"):
            response_text = response_text[7:-3].strip()

        # Phân tích chuỗi JSON trả về
        result = json.loads(response_text)

        # Kiểm tra cấu trúc của JSON
        if "match_score" in result and "ai_analysis" in result:
            logging.info(f"Phân tích thành công. Điểm phù hợp: {result['match_score']}")
            return result
        else:
            logging.error(f"Lỗi: JSON trả về không đúng cấu trúc. Response: {response_text}")
            return None

    except json.JSONDecodeError:
        logging.error(f"Lỗi giải mã JSON. Model có thể đã không trả về JSON hợp lệ. Response: {response_text}")
        return None
    except Exception as e:
        logging.error(f"Lỗi không xác định trong quá trình phân tích: {e}")
        return None

if __name__ == '__main__':
    # --- Dành cho việc chạy thử nghiệm ---
    print("Bắt đầu chạy thử nghiệm module `analyzer`...")

    try:
        # 1. Lấy CV index
        print("\n--- Bước 1: Tải/Tạo CV Index ---")
        cv_index = get_cv_index()
        print("Tải CV Index thành công.")

        # 2. Cấu hình Query Engine
        print("\n--- Bước 2: Cấu hình LLM và Query Engine ---")
        # Đảm bảo bạn đã cài đặt và chạy Ollama với model 'phi3:mini'
        # Lệnh để chạy: `ollama run phi3:mini`
        try:
            query_engine = setup_llm_and_query_engine(cv_index)
            print("Cấu hình Query Engine thành công.")
        except Exception as e:
            print(f"\nLỖI: Không thể kết nối đến Ollama hoặc cấu hình LLM.")
            print("Hãy đảm bảo bạn đã cài đặt Ollama và chạy lệnh: `ollama run phi3:mini`")
            print(f"Chi tiết lỗi: {e}")
            exit()
            
        # 3. Phân tích một JD mẫu
        print("\n--- Bước 3: Phân tích một Job Description mẫu ---")
        sample_jd = """
        **Senior Python Developer (ETL & Data Pipelines)**
        - Yêu cầu 5 năm kinh nghiệm với Python.
        - Có kinh nghiệm sâu sắc trong việc xây dựng các hệ thống ETL, xử lý dữ liệu lớn.
        - Thành thạo các framework như Django, FastAPI.
        - Biết sử dụng Scrapy là một lợi thế lớn.
        - Kỹ năng làm việc với PostgreSQL và các cơ sở dữ liệu quan hệ.
        """
        
        analysis_result = analyze_job_description(query_engine, sample_jd)

        if analysis_result:
            print("\nKết quả phân tích:")
            print(json.dumps(analysis_result, indent=2, ensure_ascii=False))
        else:
            print("\nKhông nhận được kết quả phân tích hợp lệ.")

    except FileNotFoundError as e:
        print(f"\nLỖI: {e}")
    except Exception as e:
        print(f"\nĐã xảy ra lỗi không mong muốn: {e}")

    print("\nThử nghiệm module `analyzer` hoàn tất!")
