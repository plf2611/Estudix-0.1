"""
Modelos de dados para o Study Assistant
"""
import os
import uuid
from datetime import datetime
from pathlib import Path
import json

# Diretório de dados para armazenamento dos modelos
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

class User:
    """Modelo para usuários do sistema"""
    
    USERS_FILE = DATA_DIR / "users.json"
    
    def __init__(self, name, email=None, user_id=None):
        """
        Inicializa um usuário
        
        Args:
            name (str): Nome do usuário
            email (str, optional): Email do usuário
            user_id (str, optional): ID do usuário. Se não fornecido, será gerado.
        """
        self.name = name
        self.email = email
        self.user_id = user_id or str(uuid.uuid4())
        self.created_at = datetime.now().isoformat()
        self.last_login = datetime.now().isoformat()
    
    def to_dict(self):
        """Converte o usuário para um dicionário"""
        return {
            "user_id": self.user_id,
            "name": self.name,
            "email": self.email,
            "created_at": self.created_at,
            "last_login": self.last_login
        }
    
    @classmethod
    def from_dict(cls, data):
        """Cria um usuário a partir de um dicionário"""
        user = cls(
            name=data["name"],
            email=data.get("email"),
            user_id=data["user_id"]
        )
        user.created_at = data["created_at"]
        user.last_login = data["last_login"]
        return user
    
    @classmethod
    def load_users(cls):
        """Carrega todos os usuários do arquivo"""
        if not cls.USERS_FILE.exists():
            return []
        
        try:
            with open(cls.USERS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return [cls.from_dict(user_data) for user_data in data]
        except Exception as e:
            print(f"Erro ao carregar usuários: {e}")
            return []
    
    @classmethod
    def save_users(cls, users):
        """Salva todos os usuários no arquivo"""
        try:
            with open(cls.USERS_FILE, "w", encoding="utf-8") as f:
                json.dump([user.to_dict() for user in users], f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"Erro ao salvar usuários: {e}")
            return False
    
    @classmethod
    def get_by_id(cls, user_id):
        """Busca um usuário pelo ID"""
        users = cls.load_users()
        for user in users:
            if user.user_id == user_id:
                return user
        return None
    
    @classmethod
    def get_by_email(cls, email):
        """Busca um usuário pelo email"""
        if not email:
            return None
            
        users = cls.load_users()
        for user in users:
            if user.email and user.email.lower() == email.lower():
                return user
        return None
    
    def save(self):
        """Salva ou atualiza um usuário"""
        users = self.load_users()
        
        # Verifica se o usuário já existe
        for i, user in enumerate(users):
            if user.user_id == self.user_id:
                users[i] = self
                return self.save_users(users)
        
        # Novo usuário
        users.append(self)
        return self.save_users(users)
    
    def update_last_login(self):
        """Atualiza a data do último login"""
        self.last_login = datetime.now().isoformat()
        return self.save()


class ChatHistory:
    """Modelo para histórico de chat"""
    
    HISTORY_DIR = DATA_DIR / "chat_history"
    HISTORY_DIR.mkdir(exist_ok=True)
    
    def __init__(self, user_id):
        """
        Inicializa um histórico de chat
        
        Args:
            user_id (str): ID do usuário associado
        """
        self.user_id = user_id
        self.history_file = self.HISTORY_DIR / f"{user_id}.json"
        self.messages = self._load_messages()
    
    def _load_messages(self):
        """Carrega as mensagens do arquivo"""
        if not self.history_file.exists():
            return []
        
        try:
            with open(self.history_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Erro ao carregar histórico de chat: {e}")
            return []
    
    def save_messages(self):
        """Salva as mensagens no arquivo"""
        try:
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump(self.messages, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"Erro ao salvar histórico de chat: {e}")
            return False
    
    def add_message(self, role, content):
        """
        Adiciona uma mensagem ao histórico
        
        Args:
            role (str): Papel do remetente ("user" ou "assistant")
            content (str): Conteúdo da mensagem
        """
        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        }
        
        self.messages.append(message)
        
        # Manter apenas as últimas 10 mensagens
        if len(self.messages) > 10:
            self.messages = self.messages[-10:]
        
        return self.save_messages()
    
    def get_messages(self, limit=10):
        """
        Retorna as últimas mensagens do histórico
        
        Args:
            limit (int): Número máximo de mensagens para retornar
        """
        return self.messages[-limit:]
    
    def clear_history(self):
        """Limpa o histórico de chat"""
        self.messages = []
        return self.save_messages()


class UserPreferences:
    """Modelo para preferências de usuário"""
    
    PREFS_DIR = DATA_DIR / "preferences"
    PREFS_DIR.mkdir(exist_ok=True)
    
    def __init__(self, user_id):
        """
        Inicializa as preferências de um usuário
        
        Args:
            user_id (str): ID do usuário associado
        """
        self.user_id = user_id
        self.prefs_file = self.PREFS_DIR / f"{user_id}.json"
        self.preferences = self._load_preferences()
    
    def _load_preferences(self):
        """Carrega as preferências do arquivo"""
        default_prefs = {
            "theme": "dark",
            "notifications_enabled": True,
            "voice_assistant_enabled": True,
            "study_duration": 25  # Minutos
        }
        
        if not self.prefs_file.exists():
            return default_prefs
        
        try:
            with open(self.prefs_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Erro ao carregar preferências: {e}")
            return default_prefs
    
    def save_preferences(self):
        """Salva as preferências no arquivo"""
        try:
            with open(self.prefs_file, "w", encoding="utf-8") as f:
                json.dump(self.preferences, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"Erro ao salvar preferências: {e}")
            return False
    
    def get_preference(self, key, default=None):
        """
        Obtém uma preferência específica
        
        Args:
            key (str): Chave da preferência
            default: Valor padrão caso a preferência não exista
        """
        return self.preferences.get(key, default)
    
    def set_preference(self, key, value):
        """
        Define uma preferência
        
        Args:
            key (str): Chave da preferência
            value: Valor da preferência
        """
        self.preferences[key] = value
        return self.save_preferences()