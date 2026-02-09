class ResourceNotFoundException(Exception):
    """
    custom exception when a resource not found
    """

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class InvalidCredentialsException(Exception):
    """
    custom exception when invalid credentials are provided
    """

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class UnauthorizedAccessException(Exception):
    """
    custom exception when access is unauthorized
    """

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ResourceAlreadyExistsException(Exception):
    """
    custom exception when a resource already exists
    """

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ValidationException(Exception):
    """
    custom exception when validation fails
    """

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class InvalidOperationException(Exception):
    """
    custom exception when an invalid operation is attempted
    """

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message
