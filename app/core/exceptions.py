"""
Custom application exceptions.
"""

from fastapi import HTTPException, status


class AppException(HTTPException):
    """Base application exception."""
    
    def __init__(self, detail: str, status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR):
        super().__init__(status_code=status_code, detail=detail)


class NotFoundException(AppException):
    """Resource not found exception."""
    
    def __init__(self, detail: str = "Resource not found"):
        super().__init__(detail=detail, status_code=status.HTTP_404_NOT_FOUND)


class UnauthorizedException(AppException):
    """Unauthorized access exception."""
    
    def __init__(self, detail: str = "Unauthorized"):
        super().__init__(detail=detail, status_code=status.HTTP_401_UNAUTHORIZED)


class BadRequestException(AppException):
    """Bad request exception."""
    
    def __init__(self, detail: str = "Bad request"):
        super().__init__(detail=detail, status_code=status.HTTP_400_BAD_REQUEST)

