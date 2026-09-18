import os
import imaplib
import email

from email.header import decode_header, make_header
from html.parser import HTMLParser

from dotenv import load_dotenv


# 读取项目目录下的 .env
load_dotenv()

EMAIL_ADDRESS = os.getenv("SMAIL_EMAIL")
EMAIL_PASSWORD = os.getenv("SMAIL_PASSWORD")

IMAP_SERVER = "imap.exmail.qq.com"
IMAP_PORT = 993


# --------------------------------------------------
# HTML -> 纯文本
# --------------------------------------------------

class HTMLTextParser(HTMLParser):

    def __init__(self):
        super().__init__()
        self.parts = []

    # 遇到开始标签
    def handle_starttag(self, tag, attrs):

        # 这些标签一般表示新的一段内容
        if tag in ["p", "div", "br", "li", "tr"]:
            self.parts.append("\n")

    # 遇到结束标签
    def handle_endtag(self, tag):

        if tag in ["p", "div", "li", "tr"]:
            self.parts.append("\n")

    # 真正的文字内容
    def handle_data(self, data):
        self.parts.append(data)

    # 最终得到纯文本
    def get_text(self):

        text = "".join(self.parts)

        # 清理每一行前后的空格
        lines = []

        for line in text.splitlines():

            line = line.strip()

            if line:
                lines.append(line)

        return "\n".join(lines)


def html_to_text(html):

    parser = HTMLTextParser()

    parser.feed(html)

    return parser.get_text()


# --------------------------------------------------
# 解码邮件某一部分
# --------------------------------------------------

def decode_part(part):

    payload = part.get_payload(decode=True)

    if payload is None:
        return ""

    charset = part.get_content_charset()

    if charset is None:
        charset = "utf-8"

    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


# --------------------------------------------------
# 提取邮件正文
# --------------------------------------------------

def extract_body(message):

    plain_body = ""
    html_body = ""

    # 如果邮件是 multipart
    if message.is_multipart():

        for part in message.walk():

            content_type = part.get_content_type()

            # 有些邮件会把图片、附件等放在这里
            # 我们只关心正文
            if part.get_content_disposition() == "attachment":
                continue

            if content_type == "text/plain":

                if not plain_body:
                    plain_body = decode_part(part)

            elif content_type == "text/html":

                if not html_body:
                    html_body = decode_part(part)

    else:

        content_type = message.get_content_type()

        if content_type == "text/plain":
            plain_body = decode_part(message)

        elif content_type == "text/html":
            html_body = decode_part(message)

    # 如果存在纯文本正文，优先使用纯文本
    if plain_body.strip():
        return plain_body.strip()

    # 否则把 HTML 转成纯文本
    if html_body.strip():
        return html_to_text(html_body)

    return ""


# --------------------------------------------------
# 获取最近邮件
# --------------------------------------------------

def get_recent_emails():

    mail = imaplib.IMAP4_SSL(
        IMAP_SERVER,
        IMAP_PORT
    )

    try:

        # 登录
        mail.login(
            EMAIL_ADDRESS,
            EMAIL_PASSWORD
        )

        # 打开收件箱
        mail.select("INBOX", readonly=True)

        # 搜索所有邮件
        status, messages = mail.search(None, "ALL")

        if status != "OK":
            return []

        email_ids = messages[0].split()

        # 最多获取最近 5 封
        email_ids = email_ids[-5:]

        results = []

        for email_id in email_ids:

            status, data = mail.fetch(
                email_id,
                "(RFC822)"
            )

            if status != "OK":
                continue

            raw_email = data[0][1]

            message = email.message_from_bytes(raw_email)

            # 解码主题
            subject = str(
                make_header(
                    decode_header(
                        message.get("Subject", "")
                    )
                )
            )

            # 解码发件人
            sender = str(
                make_header(
                    decode_header(
                        message.get("From", "")
                    )
                )
            )

            # 获取时间
            date = message.get("Date", "")

            # 获取正文
            body = extract_body(message)

            results.append({
                "subject": subject,
                "sender": sender,
                "date": date,
                "body": body
            })

        return results

    finally:

        try:
            mail.close()
        except:
            pass

        mail.logout()