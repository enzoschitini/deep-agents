
from deep_agents.memory.storage.storage_memory import StorageMemory

class MemoryBuilder:
    def __init__(self):
        pass

    def storage_memory(self, database):
        storage = StorageMemory(database=database)
        messages = storage.get_messagens()
        return messages
