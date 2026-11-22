from deep_agents.memory.storage.local_csv import LocalCSV
from deep_agents.memory.storage.fake_vectorial import FakeVectorialDatabase


class StorageMemory:
    "Gerencia a memoria em armazenamento. Por enquanto via arquivo CSV mas futuramente via banco de dados (PostgreSQL e até mesm Pinecone para memoria vectorial)"
    def __init__(self, database):
        self.database = database
        self._db_instance = self._resolve_database()

    def _resolve_database(self):
        if self.database == "local_csv":
            return LocalCSV(file_path="messages.csv")
        elif self.database == "fake_vectorial":
            return FakeVectorialDatabase()
        else:
            raise ValueError(f"Tipo de banco de dados desconhecido: {self.database}")

    def get_message(self):
        # Busca pelo ID de uma mensagem
        pass

    def get_messagens(self):
        # Busca pelo ID de uma sessão
        pass

    def save_message(self):
        # Salva uma mensagem via ID
        pass
