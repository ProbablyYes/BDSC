import textract
import sys

if len(sys.argv) < 2:
    print("用法: python test_textract.py <doc文件路径>")
    sys.exit(1)

file_path = sys.argv[1]
try:
    text = textract.process(file_path)
    print("提取内容前200字符:")
    print(text[:200].decode("utf-8", errors="ignore"))
except Exception as e:
    print(f"textract 解析失败: {e}")
