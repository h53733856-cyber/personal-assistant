from tools.email import get_recent_emails


print("Personal Assistant started!")

emails = get_recent_emails()

for mail in emails:

    print()
    print("================================")
    print("主题：", mail["subject"])
    print("发件人：", mail["sender"])
    print("时间：", mail["date"])
    print("正文：")
    print(mail["body"])