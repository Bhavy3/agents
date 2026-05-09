class FridayError(Exception):
    pass

class ValidationError(FridayError):
    pass

class TimeoutError(FridayError):
    pass

class WorkerFailureError(FridayError):
    pass

class ExecutorError(FridayError):
    pass

class QueueOverflowError(FridayError):
    pass

class ContractViolationError(FridayError):
    pass
