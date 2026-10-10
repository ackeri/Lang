class CompileError(Exception):
    def __init__(self, message, line=None):
        super().__init__(message)
        self.message = message
        self.line = line

    def __str__(self):
        if self.line is None:
            return self.message
        return f"line {self.line}: {self.message}"
