"""
 نقطة دخول بديلة — تستدعي bot.main()
 بعض المستخدمين يضعون `python main.py` في workflow، هذا الملف يضمن عمل الأمرين.
"""
from bot import main

if __name__ == "__main__":
    main()
