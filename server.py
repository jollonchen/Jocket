from http.server import BaseHTTPRequestHandler, HTTPServer
class S(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        with open('dom.txt', 'wb') as f:
            f.write(post_data)
        self.send_response(200)
        self.end_headers()

HTTPServer(('', 8000), S).serve_forever()
