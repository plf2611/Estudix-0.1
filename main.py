#!/usr/bin/env python3
"""
Study Assistant Web - A personal assistant for students
"""
import os
import time
import logging
import json
import schedule
import datetime
import threading
import pytz
import uuid
from flask import Flask, render_template, request, redirect, url_for, jsonify, send_file, session, flash, g
from pathlib import Path
from assistant.schedule_manager import ScheduleManager
from assistant.text_generator_new import TextGenerator, ChatAssistant
from assistant.speech_converter import SpeechConverter
from assistant.audio_player import AudioPlayer
from assistant.gamification import GamificationManager
from assistant.image_analyzer import ImageAnalyzer
from assistant.google_calendar import GoogleCalendarManager
from assistant.ical_exporter import ICalExporter
from models import User, ChatHistory, UserPreferences
import config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("assistant.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Create Flask app
app = Flask(__name__, static_folder='static', static_url_path='/static')
app.secret_key = os.environ.get("SESSION_SECRET", "study-assistant-secret-key")

# User session management
@app.before_request
def load_logged_in_user():
    """Load logged in user data before each request"""
    user_id = session.get('user_id')
    if user_id is None:
        g.user = None
    else:
        g.user = User.get_by_id(user_id)
        
    # Create or ensure data directories exist
    os.makedirs("data", exist_ok=True)
    os.makedirs("data/chat_history", exist_ok=True)
    os.makedirs("data/preferences", exist_ok=True)

# Initialize components
schedule_manager = ScheduleManager()
text_generator = TextGenerator()
speech_converter = SpeechConverter()
audio_player = AudioPlayer()
chat_assistant = ChatAssistant()
# Inicializar o gerenciador de gamificação
gamification_manager = GamificationManager()
# Inicializar o analisador de imagens
image_analyzer = ImageAnalyzer()
# Inicializar o exportador iCalendar
ical_exporter = ICalExporter()
last_generated_audio = None
is_running = True

# Ensure data is loaded
try:
    schedule_manager.load_schedule()
    logger.info("Schedule data loaded successfully")
except Exception as e:
    logger.warning(f"Could not load schedule data: {e}")
    logger.info("Creating new schedule")
    schedule_manager.create_new_schedule()

# Definir fuso horário
TIMEZONE = pytz.timezone('America/Sao_Paulo')  # Fuso horário de Brasília

# Schedule alarms
def schedule_alarms():
    """Schedule all alarms from the schedule"""
    # Clear existing schedules
    schedule.clear()
    
    schedule_data = schedule_manager.get_schedule()
    alarms = schedule_data.get('alarms', [])
    
    for alarm in alarms:
        time_str = alarm['time']
        days = alarm['days']
        
        # Map day abbreviations to schedule's day strings
        day_mapping = {
            'Mon': 'monday', 'Tue': 'tuesday', 'Wed': 'wednesday',
            'Thu': 'thursday', 'Fri': 'friday', 'Sat': 'saturday', 'Sun': 'sunday',
            'Seg': 'monday', 'Ter': 'tuesday', 'Qua': 'wednesday',
            'Qui': 'thursday', 'Sex': 'friday', 'Sab': 'saturday', 'Dom': 'sunday'
        }
        
        for day in days:
            if day in day_mapping:
                schedule_day = day_mapping[day]
                # Usar o fuso horário de Brasília para o agendamento
                getattr(schedule.every(), schedule_day).at(time_str).do(trigger_alarm)
                logger.info(f"Agendado alarme para {day} às {time_str} (Horário de Brasília)")
    
    logger.info(f"Agendados {len(alarms)} alarmes no total")

def trigger_alarm():
    """Trigger the alarm when scheduled time is reached"""
    logger.info("Alarm triggered")
    global last_generated_audio
    
    try:
        schedule_data = schedule_manager.get_schedule()
        message = text_generator.generate_daily_message(schedule_data)
        audio_file = speech_converter.convert_text_to_speech(message)
        last_generated_audio = audio_file
        
        logger.info("Alarm completed successfully")
        return True
    except Exception as e:
        logger.error(f"Error during alarm trigger: {e}")
        return False

def background_scheduler():
    """Run the scheduler in the background"""
    while is_running:
        schedule.run_pending()
        time.sleep(1)

# Start the scheduler in a background thread
scheduler_thread = threading.Thread(target=background_scheduler, daemon=True)
scheduler_thread.start()
schedule_alarms()

# Authentication routes
@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login page"""
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        
        if not name:
            flash("Nome é obrigatório")
            return redirect(url_for('login'))
        
        # Verificar se usuário existe
        user = None
        if email:
            user = User.get_by_email(email)
        
        # Se não existe, criar novo usuário
        if not user:
            user = User(name=name, email=email)
            user.save()
            flash("Novo usuário criado com sucesso!")
        else:
            # Atualizar dados do usuário existente
            user.name = name  # Atualizar nome se alterado
            user.update_last_login()
            flash(f"Bem-vindo de volta, {name}!")
        
        # Definir sessão
        session.clear()
        session['user_id'] = user.user_id
        
        return redirect(url_for('index'))
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    """Logout route"""
    session.clear()
    flash("Logout realizado com sucesso!")
    return redirect(url_for('index'))

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    """User profile page"""
    if not g.user:
        flash("Você precisa estar logado para acessar seu perfil")
        return redirect(url_for('login'))
    
    # Carregar preferências do usuário
    user_prefs = UserPreferences(g.user.user_id)
    
    # Obter histórico de chat
    chat_history = ChatHistory(g.user.user_id)
    
    # Processar formulários POST
    if request.method == 'POST':
        form_type = request.form.get('form_type')
        
        # Atualizar preferências
        if form_type == 'preferences':
            notifications_enabled = request.form.get('notifications_enabled') == 'on'
            voice_assistant_enabled = request.form.get('voice_assistant_enabled') == 'on'
            
            try:
                study_duration = int(request.form.get('study_duration', 25))
                if study_duration < 5:
                    study_duration = 5
                elif study_duration > 120:
                    study_duration = 120
            except:
                study_duration = 25
            
            user_prefs.set_preference('notifications_enabled', notifications_enabled)
            user_prefs.set_preference('voice_assistant_enabled', voice_assistant_enabled)
            user_prefs.set_preference('study_duration', study_duration)
            
            flash("Preferências atualizadas com sucesso!")
            
        # Limpar histórico
        elif form_type == 'clear_history':
            chat_history.clear_history()
            flash("Histórico de conversas limpo com sucesso!")
    
    # Obter mensagens recentes para exibição
    recent_messages = chat_history.get_messages(10)
    
    return render_template('profile.html', 
                          user=g.user, 
                          preferences=user_prefs.preferences,
                          chat_history=recent_messages)

# Routes
@app.route('/')
def index():
    """Home page"""
    # Agora não precisamos mais informar o status da API na página inicial
    # porque temos uma chave de API padrão que funciona para demonstração
    return render_template('index.html')

@app.route('/schedule')
def view_schedule():
    """View schedule page"""
    schedule_data = schedule_manager.get_schedule()
    return render_template('schedule.html', schedule=schedule_data)

@app.route('/subjects', methods=['GET', 'POST'])
def manage_subjects():
    """Manage subjects page"""
    if request.method == 'POST':
        subjects = []
        subject_names = request.form.getlist('subject_name')
        subject_hours = request.form.getlist('subject_hours')
        
        for i in range(len(subject_names)):
            if subject_names[i].strip():
                try:
                    hours = float(subject_hours[i])
                    subjects.append({
                        "name": subject_names[i].strip(),
                        "hours_per_week": hours
                    })
                except ValueError:
                    flash("Please enter valid hours for all subjects.")
                    break
        
        if subjects:
            schedule_manager.update_subjects(subjects)
            flash("Subjects updated successfully!")
        
        return redirect(url_for('manage_subjects'))
    
    schedule_data = schedule_manager.get_schedule()
    return render_template('subjects.html', subjects=schedule_data.get('subjects', []))

@app.route('/alarms', methods=['GET', 'POST'])
def manage_alarms():
    """Manage alarms page"""
    if request.method == 'POST':
        time_input = request.form.get('alarm_time')
        days_input = request.form.get('alarm_days')
        subject_input = request.form.get('subject', None)  # Obter matéria (opcional)
        
        # Se a matéria estiver vazia, definir como None
        if subject_input and subject_input.strip() == '':
            subject_input = None
        
        if time_input and days_input:
            try:
                # Validate time format
                datetime.datetime.strptime(time_input, "%H:%M")
                days = [day.strip() for day in days_input.split(',')]
                
                # Add the alarm with subject information
                schedule_manager.add_alarm({
                    "time": time_input,
                    "days": days,
                    "subject": subject_input  # Pode ser None se não fornecido
                })
                flash("Alarme adicionado com sucesso!")
                
                # Reschedule alarms
                schedule_alarms()
            except ValueError:
                flash("Formato de horário inválido. Use o formato HH:MM.")
        else:
            flash("Alarme não adicionado. Informações incompletas.")
        
        return redirect(url_for('manage_alarms'))
    
    schedule_data = schedule_manager.get_schedule()
    return render_template('alarms.html', alarms=schedule_data.get('alarms', []))

@app.route('/delete_alarm/<int:index>', methods=['POST'])
def delete_alarm(index):
    """Delete an alarm"""
    if schedule_manager.remove_alarm(index):
        flash("Alarm removed successfully!")
        schedule_alarms()
    else:
        flash("Failed to remove alarm.")
    return redirect(url_for('manage_alarms'))

@app.route('/test_alarm', methods=['GET', 'POST'])
def test_alarm():
    """Test alarm page"""
    global last_generated_audio
    message = ""
    audio_path = ""
    success = False
    is_audio_file = False
    
    # APIs sempre disponíveis para demonstração
    api_status = {
        'google': True,
        'elevenlabs': True
    }
    
    # Determinar se deve usar a API (do formulário ou da URL)
    use_api = False
    if request.method == 'POST':
        use_api = request.form.get('test_type') == 'api'
    else:
        use_api = request.args.get('use_api', '0') == '1'
    
    schedule_data = schedule_manager.get_schedule()
    
    # Diretório para salvar os áudios de exemplo
    audio_dir = Path("data/audio")
    os.makedirs(audio_dir, exist_ok=True)
    
    # Mensagens de exemplo para diferentes ocasiões
    example_messages = {
        'default': "Este é um teste de alarme. O assistente de estudos está funcionando corretamente. Quando configurado, você receberá mensagens personalizadas para seus estudos.",
        'morning': "Bom dia! Hoje você tem aulas de matemática e história. Não se esqueça de revisar as equações e as datas importantes.",
        'afternoon': "Boa tarde! Hora de estudar física e química. Lembre-se de fazer os exercícios práticos.",
        'evening': "Boa noite! Reserve um tempo para revisar o conteúdo estudado hoje antes de dormir."
    }
    
    # Para fins de teste, escolher uma mensagem aleatória
    import random
    random_key = random.choice(list(example_messages.keys()))
    example_message = example_messages[random_key]
    
    if request.method == 'POST' or not audio_path:
        try:
            if use_api:  # Sempre tentamos usar a API quando solicitado
                # Usar as APIs para gerar mensagem e áudio
                logger.info("Gerando alarme de teste usando APIs (Google Gemini + ElevenLabs)")
                
                # 1. Primeiro gerar a mensagem com Google Gemini
                logger.info("Gerando mensagem personalizada com Google Gemini")
                
                # Para testes, adicionar algumas matérias caso não existam 
                # para poder testar a geração de mensagens mesmo sem cadastro
                test_schedule = schedule_data.copy() if schedule_data else {}
                if not test_schedule.get('subjects') or len(test_schedule.get('subjects', [])) == 0:
                    # Criar matérias de exemplo apenas para teste
                    logger.info("Criando matérias de teste para demonstração")
                    test_schedule['subjects'] = [
                        {"name": "Matemática", "hours_per_week": 6},
                        {"name": "Português", "hours_per_week": 4},
                        {"name": "Ciências", "hours_per_week": 3},
                        {"name": "História", "hours_per_week": 3},
                        {"name": "Geografia", "hours_per_week": 2}
                    ]
                
                # Chamar a API do Google Gemini para gerar a mensagem
                message = text_generator.generate_daily_message(test_schedule)
                logger.info(f"Mensagem gerada pelo Gemini: {message[:100]}...")
                
                # 2. Converter a mensagem em áudio usando ElevenLabs
                logger.info("Convertendo mensagem para áudio com ElevenLabs")
                audio_file = speech_converter.convert_text_to_speech(message)
                is_audio_file = True
            else:
                # Não usar as APIs - criar arquivo de texto como fallback
                logger.info("Usando mensagem de exemplo (modo simples)")
                message = example_message
                example_audio_file = audio_dir / f"alarme_exemplo_{int(time.time())}.txt"
                with open(example_audio_file, "w") as f:
                    f.write(message)
                audio_file = str(example_audio_file)
                is_audio_file = False
            
            last_generated_audio = audio_file
            audio_path = os.path.basename(audio_file)
            success = True
            
            logger.info(f"Alarme de teste gerado: {audio_file}")
            flash("Alarme de teste gerado com sucesso!")
            
            # Não reproduzimos mais o áudio no servidor - o browser do usuário vai reproduzir
            if is_audio_file and os.path.exists(audio_file):
                logger.info(f"Áudio gerado e pronto para ser reproduzido pelo navegador: {audio_file}")
            
        except Exception as e:
            logger.error(f"Erro durante o teste do alarme: {str(e)}")
            flash(f"Erro ao gerar alarme: Verifique as configurações das APIs")
    
    api_message = ""  # Não precisamos mais mostrar mensagens sobre APIs não configuradas
    
    return render_template('test_alarm.html', 
                          message=message, 
                          audio_path=audio_path, 
                          success=success,
                          use_api=use_api,
                          api_status=api_status,
                          api_message=api_message,
                          is_audio_file=is_audio_file)

@app.route('/play_audio/<path:filename>')
def play_audio(filename):
    """Serve the audio file"""
    try:
        audio_dir = Path("data/audio")
        return send_file(audio_dir / filename)
    except Exception as e:
        logger.error(f"Error serving audio file: {e}")
        return "Audio file not found", 404

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    """Settings page"""
    if request.method == 'POST':
        elevenlabs_key = request.form.get('elevenlabs_key')
        google_key = request.form.get('google_key')
        
        if elevenlabs_key:
            os.environ['ELEVENLABS_API_KEY'] = elevenlabs_key
            flash("ElevenLabs API Key updated")
            
        if google_key:
            os.environ['GOOGLE_API_KEY'] = google_key
            flash("Google API Key updated")
        
        return redirect(url_for('settings'))
    
    # APIs sempre disponíveis para demonstração
    api_status = {
        'google': True,
        'elevenlabs': True
    }
    return render_template('settings.html', api_status=api_status)

@app.route('/assistant')
def assistant_page():
    """Assistant chat page"""
    # Não é mais necessário verificar o status da API
    return render_template('assistant_chat.html')

@app.route('/assistant_chat', methods=['POST'])
def process_chat():
    """Process chat messages and return responses"""
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400
    
    data = request.get_json()
    user_message = data.get('message', '')
    
    if not user_message:
        return jsonify({"error": "No message provided"}), 400
    
    try:
        # O ChatAssistant tem uma chave padrão para fins de demonstração
        # e já tratará automaticamente casos de erro, portanto não precisamos
        # mostrar aviso de API não configurada quando a resposta for gerada com sucesso
        
        # Extrair o histórico do chat da sessão ou inicializar
        chat_history = session.get('chat_history', [])
        
        # Obter os dados do cronograma para contexto
        schedule_data = schedule_manager.get_schedule()
        
        # Obter resposta do assistente
        response = chat_assistant.get_chat_response(user_message, chat_history, schedule_data)
        
        # Adicionar a interação ao histórico
        chat_history.append({"role": "user", "content": user_message})
        chat_history.append({"role": "assistant", "content": response})
        
        # Manter apenas as últimas 10 interações (20 mensagens)
        if len(chat_history) > 20:
            chat_history = chat_history[-20:]
        
        # Salvar o histórico atualizado na sessão
        session['chat_history'] = chat_history
        
        # Se o usuário estiver logado, salvar o histórico também no seu perfil
        if hasattr(g, 'user') and g.user:
            try:
                user_chat_history = ChatHistory(g.user.user_id)
                user_chat_history.add_message("user", user_message)
                user_chat_history.add_message("assistant", response)
            except Exception as history_error:
                logger.error(f"Erro ao salvar histórico do usuário: {str(history_error)}")
                # Continuar mesmo se falhar ao salvar o histórico
        
        # Verificar se é um comando para criar alarme
        if ("criar alarme" in user_message.lower() or 
            "adicionar alarme" in user_message.lower() or 
            "novo alarme" in user_message.lower() or
            "agendar alarme" in user_message.lower() or
            "configurar alarme" in user_message.lower()):
            # Implementar lógica para extrair horário e dias do alarme
            import re
            
            # Tentar extrair horário (formatos: 14h, 14:30, 14h30, 14.30, 2 da tarde, etc.)
            time_patterns = [
                r'(\d{1,2})[h:](\d{1,2})',  # 14h30, 14:30
                r'(\d{1,2})[h\s]',           # 14h, 14 horas
                r'(\d{1,2})[\s]?(?:da|hrs|horas|h)',  # 2 da tarde, 14 hrs
                r'às[\s]+(\d{1,2})',         # às 14
                r'as[\s]+(\d{1,2})',         # as 14
                r'para[\s]+(\d{1,2})',       # para 14
            ]
            
            extracted_hour = None
            extracted_minute = 0
            
            for pattern in time_patterns:
                time_match = re.search(pattern, user_message, re.IGNORECASE)
                if time_match:
                    # Se encontrou um padrão com hora e minuto
                    if len(time_match.groups()) > 1 and time_match.group(2):
                        extracted_hour = int(time_match.group(1))
                        extracted_minute = int(time_match.group(2))
                        break
                    # Se encontrou só a hora
                    else:
                        extracted_hour = int(time_match.group(1))
                        break
            
            # Se não encontrou horário, tentar padrões mais simples
            if extracted_hour is None:
                simple_time_match = re.search(r'(\d{1,2})', user_message)
                if simple_time_match:
                    extracted_hour = int(simple_time_match.group(1))
            
            # Verificar se deve ajustar para PM com base no contexto
            if extracted_hour is not None and extracted_hour < 12:
                if any(term in user_message.lower() for term in ['tarde', 'noite', 'pm', 'p.m.', 'evening']):
                    extracted_hour += 12
            
            # Se encontrou um horário válido, criar o alarme
            if extracted_hour is not None and 0 <= extracted_hour < 24 and 0 <= extracted_minute < 60:
                time_str = f"{extracted_hour:02d}:{extracted_minute:02d}"
                
                # Tentar extrair dias da semana
                days = ["Seg", "Ter", "Qua", "Qui", "Sex"]  # Padrão para dias úteis
                
                # Procurar menções a dias específicos
                day_patterns = {
                    "segunda": "Seg", "seg": "Seg", 
                    "terça": "Ter", "ter": "Ter", 
                    "quarta": "Qua", "qua": "Qua", 
                    "quinta": "Qui", "qui": "Qui", 
                    "sexta": "Sex", "sex": "Sex", 
                    "sábado": "Sab", "sab": "Sab", 
                    "domingo": "Dom", "dom": "Dom",
                    "fim de semana": ["Sab", "Dom"],
                    "final de semana": ["Sab", "Dom"]
                }
                
                # Procurar matéria mencionada 
                subject = None
                schedule_data = schedule_manager.get_schedule()
                subjects = schedule_data.get('subjects', [])
                
                if subjects:
                    for subject_item in subjects:
                        subject_name = subject_item['name'].lower()
                        if subject_name in user_message.lower():
                            subject = subject_name
                            break
                
                # Se houver menção a dias específicos, usar esses dias
                custom_days = []
                for day_keyword, day_code in day_patterns.items():
                    if day_keyword in user_message.lower():
                        if isinstance(day_code, list):
                            custom_days.extend(day_code)
                        else:
                            custom_days.append(day_code)
                
                if custom_days:
                    # Remover duplicatas mantendo a ordem
                    days = list(dict.fromkeys(custom_days))
                
                # Verificar se há menção a "todos os dias"
                if any(term in user_message.lower() for term in ['todos os dias', 'diariamente', 'cada dia']):
                    days = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sab", "Dom"]
                
                # Criar o alarme
                try:
                    # Adicionar o alarme
                    schedule_manager.add_alarm({
                        "time": time_str,
                        "days": days,
                        "subject": subject  # Pode ser None se não for especificada
                    })
                    
                    # Salvar as mudanças
                    schedule_manager.save_schedule()
                    
                    # Reagendar alarmes
                    schedule_alarms()
                    
                    # Formatar mensagem com a matéria, se especificada
                    subject_text = f" para {subject}" if subject else ""
                    
                    # Adicionar uma resposta confirmando a criação do alarme
                    confirmation = f"\n\n✅ Alarme criado com sucesso para {time_str}{subject_text} nos dias {', '.join(days)}."
                    response += confirmation
                    
                    # Log de sucesso
                    logger.info(f"Alarme criado: {time_str} para os dias {days}, matéria: {subject}")
                except Exception as alarm_error:
                    # Log de erro
                    logger.error(f"Erro ao criar alarme: {str(alarm_error)}")
                    response += "\n\n❌ Houve um erro ao tentar criar o alarme. Por favor, tente novamente ou use a página de Alarmes."
        
        return jsonify({"response": response})
        
    except Exception as e:
        logger.error(f"Erro no processamento do chat: {str(e)}")
        return jsonify({
            "response": "Desculpe, ocorreu um erro ao processar sua mensagem. Por favor, tente novamente mais tarde."
        }), 500

# Create templates directory if it doesn't exist
os.makedirs("templates", exist_ok=True)

# API Endpoints para integrações externas
@app.route('/api/schedule', methods=['GET'])
def api_get_schedule():
    """API endpoint para obter o cronograma em formato JSON para integrações externas"""
    try:
        # Verificar se o usuário está autenticado
        if not hasattr(g, 'user') or not g.user:
            return jsonify({"error": "Autenticação necessária"}), 401
        
        # Obter o cronograma
        schedule_data = schedule_manager.get_schedule()
        
        # Se não há matérias, retornar lista vazia
        if not schedule_data or not schedule_data.get('subjects'):
            return jsonify([])
        
        # Transformar os dados para o formato esperado pela integração
        formatted_schedule = []
        days_map = {
            "Seg": "segunda-feira",
            "Ter": "terça-feira",
            "Qua": "quarta-feira",
            "Qui": "quinta-feira",
            "Sex": "sexta-feira",
            "Sab": "sábado",
            "Dom": "domingo"
        }
        
        # Se houver aulas com horários definidos
        classes = schedule_data.get('classes', [])
        for class_item in classes:
            # Extrair informações
            subject = class_item.get('subject', '')
            day_code = class_item.get('day', '')
            start_time = class_item.get('start_time', '')
            end_time = class_item.get('end_time', '')
            teacher = class_item.get('teacher', '')
            
            # Mapear código do dia para nome completo
            day = days_map.get(day_code, day_code)
            
            # Criar entrada de aula
            class_entry = {
                "title": subject,
                "description": f"Aula com {teacher}" if teacher else f"Aula de {subject}",
                "day": day,
                "start_time": start_time,
                "end_time": end_time
            }
            
            formatted_schedule.append(class_entry)
        
        # Se houver alarmes configurados, incluí-los também
        alarms = schedule_data.get('alarms', [])
        for alarm in alarms:
            time = alarm.get('time', '')
            subject = alarm.get('subject', 'Estudo')
            days = alarm.get('days', [])
            
            # Adicionar um item para cada dia do alarme
            for day_code in days:
                day = days_map.get(day_code, day_code)
                
                # Criar entrada para o alarme
                alarm_entry = {
                    "title": f"Estudo: {subject}" if subject else "Sessão de Estudo",
                    "description": f"Tempo de estudo agendado para {subject}" if subject else "Tempo de estudo agendado",
                    "day": day,
                    "start_time": time,
                    "end_time": ""  # Alarmes não têm horário de término
                }
                
                formatted_schedule.append(alarm_entry)
        
        return jsonify(formatted_schedule)
    except Exception as e:
        logger.error(f"Erro ao obter cronograma via API: {str(e)}")
        return jsonify({"error": "Erro ao processar o cronograma"}), 500

# Rotas para o sistema de gamificação
@app.route('/gamification')
def gamification():
    """Página de gamificação para visualizar streaks e conquistas"""
    # Obter estatísticas de gamificação
    stats = gamification_manager.get_study_stats()
    achievements = gamification_manager.get_all_achievements()
    study_history = gamification_manager.get_study_history(days=7)
    
    # Determinar o valor máximo para o gráfico de atividade
    max_minutes = 1  # Evitar divisão por zero
    if study_history:
        max_minutes = max(max(study_history.values()), 1)
    
    # Obter lista de matérias para o formulário de registro
    schedule_data = schedule_manager.get_schedule()
    subjects = schedule_data.get('subjects', [])
    
    return render_template('gamification.html', 
                          stats=stats,
                          achievements=achievements,
                          study_history=study_history,
                          max_minutes=max_minutes,
                          subjects=subjects)

@app.route('/gamification/record', methods=['POST'])
def record_study_session():
    """Registrar uma sessão de estudo"""
    if request.method == 'POST':
        subject = request.form.get('subject', '')
        try:
            minutes = int(request.form.get('minutes', 0))
            if minutes <= 0:
                flash("O tempo de estudo deve ser maior que zero")
                return redirect(url_for('gamification'))
            
            # Registrar a sessão de estudo
            current_streak = gamification_manager.record_study_session(minutes, subject)
            
            # Mensagem de sucesso com informação de streak
            flash(f"Sessão de estudo registrada com sucesso! Você está em uma sequência de {current_streak} dias.")
            
            return redirect(url_for('gamification'))
        except ValueError:
            flash("Por favor, insira um valor válido para o tempo de estudo")
            return redirect(url_for('gamification'))


# Rota para o Modo Estudo
@app.route('/study_mode', methods=['GET', 'POST'])
def study_mode():
    """Página de Modo Estudo focado"""
    try:
        # Verificar se há matéria e duração nos parâmetros ou usar padrões
        if request.method == 'POST':
            subject = request.form.get('subject')
            duration_min = request.form.get('duration_min', 25)
            try:
                duration_min = int(duration_min)
                if duration_min < 5:
                    duration_min = 5
                elif duration_min > 120:
                    duration_min = 120
            except:
                duration_min = 25
        else:
            subject = request.args.get('subject')
            try:
                duration_min = int(request.args.get('duration_min', 25))
                if duration_min < 5:
                    duration_min = 5
                elif duration_min > 120:
                    duration_min = 120
            except:
                duration_min = 25
        
        # Obter lista de matérias se nenhuma foi especificada
        if not subject:
            try:
                schedule_data = schedule_manager.get_schedule()
                subjects = schedule_data.get('subjects', [])
                
                if subjects:
                    # Usar a primeira matéria como padrão
                    subject = subjects[0]['name']
                else:
                    # Sem matérias cadastradas
                    subject = "Estudo Geral"
            except Exception as e:
                logger.error(f"Erro ao obter matérias do cronograma: {str(e)}")
                subject = "Estudo Geral"
        
        # Obter duração padrão das preferências do usuário, se disponível
        if hasattr(g, 'user') and g.user:
            try:
                user_prefs = UserPreferences(g.user.user_id)
                default_duration = user_prefs.get_preference('study_duration', 25)
                if not request.method == 'POST' and not request.args.get('duration_min'):
                    duration_min = default_duration
            except Exception as e:
                logger.error(f"Erro ao obter preferências do usuário: {str(e)}")
                # Continuar com o valor padrão
        
        # Se tudo der certo, mostrar a página de estudo
        return render_template('study_mode.html', subject=subject, duration_min=duration_min)
    
    except Exception as e:
        # Registrar erro e exibir uma página de erro amigável
        logger.error(f"Erro no Modo Estudo: {str(e)}")
        return render_template('error.html', 
                               title="Erro no Modo Estudo",
                               message="Não foi possível carregar o Modo Estudo. Verifique se você tem matérias cadastradas no cronograma.",
                               action_text="Voltar para o Início",
                               action_url=url_for('index'))

# Rotas para o analisador de imagens
@app.route('/analyze')
def analyze_page():
    """Página do analisador de imagens"""
    # Não é mais necessário verificar o status da API, pois temos uma chave padrão
    
    # Determinar prompt padrão
    default_prompt = """
    Analise esta imagem e forneça uma descrição detalhada do que você vê.
    Se for uma página de livro ou um documento de estudo, extraia as informações principais.
    Se for uma equação matemática, explique-a detalhadamente.
    Se for um gráfico ou diagrama, interprete o que ele representa.
    """
    
    return render_template('image_analyzer.html', default_prompt=default_prompt)

@app.route('/save_schedule_from_analysis', methods=['POST'])
def save_schedule_from_analysis():
    """Salvar cronograma a partir do resultado da análise de imagem"""
    try:
        # Obter o texto da análise 
        if not request.is_json:
            return jsonify({"success": False, "error": "É necessário enviar um JSON"}), 400
        
        data = request.get_json()
        analysis_text = data.get('analysis_text', '')
        
        if not analysis_text:
            return jsonify({"success": False, "error": "Texto da análise não fornecido"}), 400
        
        # Obter cronograma atual
        current_schedule = schedule_manager.get_schedule() or {}
        
        # Usar o mesmo gerador de texto para extrair informações estruturadas do texto
        extraction_prompt = f"""
        Extraia informações estruturadas deste texto que descreve um cronograma escolar.
        
        Texto: {analysis_text}
        
        Forneça apenas a lista de matérias no formato:
        - Nome da matéria
        - Carga horária semanal estimada (em horas)
        
        E uma lista de aulas no formato:
        - Matéria
        - Dia da semana (Seg, Ter, Qua, Qui, Sex, Sab, Dom)
        - Horário de início (HH:MM)
        - Horário de término (HH:MM)
        - Professor
        """
        
        try:
            # Solicitar ao assistente que extraia as informações em formato estruturado
            structured_info = chat_assistant.get_chat_response(extraction_prompt)
            
            # Tentar extrair matérias mencionadas
            import re
            subject_pattern = r'[-•*]\s*([^()\n-]+)(?:\s*\(?\s*(\d+)\s*(?:horas|hrs?|h)\)?)?'
            subjects_found = re.findall(subject_pattern, structured_info)
            
            # Extrair aulas
            class_pattern = r'[-•*]\s*([^:\n-]+)[\s:]+([^\s,]+)[,\s]+(\d{1,2}:\d{2})(?:\s*-\s*(\d{1,2}:\d{2}))?(?:[,\s]+(?:Prof\w*[.:])?\s*([^\n]+))?'
            classes_found = re.findall(class_pattern, structured_info)
            
            # Preparar as matérias para salvar
            subjects = []
            for subject_name, hours in subjects_found:
                name = subject_name.strip()
                # Se não tiver horas especificadas, usar 2 como padrão
                hours_per_week = int(hours) if hours else 2
                
                # Evitar duplicatas
                if not any(s.get('name') == name for s in subjects):
                    subjects.append({
                        "name": name,
                        "hours_per_week": hours_per_week
                    })
            
            # Adicionar matérias que aparecem nas aulas mas não na lista de matérias
            for class_subject, _, _, _, _ in classes_found:
                name = class_subject.strip()
                if name and not any(s.get('name') == name for s in subjects):
                    subjects.append({
                        "name": name,
                        "hours_per_week": 2  # Valor padrão
                    })
            
            # Preparar as aulas para salvar
            classes = []
            days_map = {
                'segunda': 'Seg', 'seg': 'Seg', 
                'terça': 'Ter', 'ter': 'Ter',
                'quarta': 'Qua', 'qua': 'Qua',
                'quinta': 'Qui', 'qui': 'Qui',
                'sexta': 'Sex', 'sex': 'Sex',
                'sábado': 'Sab', 'sab': 'Sab',
                'domingo': 'Dom', 'dom': 'Dom'
            }
            
            for class_subject, day, start_time, end_time, teacher in classes_found:
                # Normalizar o dia da semana
                day_code = day.strip().lower()
                day_code = days_map.get(day_code, day_code.capitalize()[:3])
                
                # Garantir que é um código de dia válido
                if day_code not in ["Seg", "Ter", "Qua", "Qui", "Sex", "Sab", "Dom"]:
                    continue
                    
                classes.append({
                    "subject": class_subject.strip(),
                    "day": day_code,
                    "start_time": start_time.strip(),
                    "end_time": end_time.strip() if end_time else "",
                    "teacher": teacher.strip() if teacher else ""
                })
                
            # Atualizar o cronograma
            current_schedule['subjects'] = subjects
            
            # Se já existem aulas, manter as existentes e adicionar as novas
            if 'classes' not in current_schedule:
                current_schedule['classes'] = []
                
            # Adicionar apenas aulas que não duplicam horários existentes
            for new_class in classes:
                if not any(c.get('day') == new_class.get('day') and 
                           c.get('start_time') == new_class.get('start_time') 
                           for c in current_schedule['classes']):
                    current_schedule['classes'].append(new_class)
            
            # Salvar o cronograma atualizado
            schedule_manager.save_schedule()
            
            return jsonify({
                "success": True, 
                "message": "Cronograma salvo com sucesso",
                "subjects_count": len(subjects),
                "classes_count": len(classes)
            })
            
        except Exception as extract_error:
            logger.error(f"Erro ao extrair informações do texto: {str(extract_error)}")
            logger.exception("Detalhes do erro:")
            return jsonify({
                "success": False,
                "error": "Não foi possível extrair informações do texto da análise"
            }), 500
            
    except Exception as e:
        logger.error(f"Erro ao salvar cronograma: {str(e)}")
        logger.exception("Detalhes do erro:")
        return jsonify({
            "success": False,
            "error": f"Erro ao processar o cronograma: {str(e)}"
        }), 500

@app.route('/analyze_image', methods=['POST'])
def analyze_image():
    """Analisar uma imagem usando o Google Gemini AI"""
    try:
        # Não precisamos mais verificar a API do Google, pois já temos uma chave padrão
        
        # Verificar se uma imagem foi enviada
        if 'image' not in request.files:
            return jsonify({
                "success": False,
                "error": "Nenhuma imagem enviada."
            })
        
        image_file = request.files['image']
        
        # Verificar se o arquivo é válido
        if image_file.filename == '':
            return jsonify({
                "success": False,
                "error": "Arquivo de imagem inválido."
            })
        
        # Verificar extensão do arquivo
        allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
        if '.' not in image_file.filename or image_file.filename.rsplit('.', 1)[1].lower() not in allowed_extensions:
            return jsonify({
                "success": False,
                "error": "Formato de arquivo não suportado. Use PNG, JPG, JPEG, GIF ou WEBP."
            })
        
        # Obter instruções personalizadas, se fornecidas
        custom_prompt = request.form.get('prompt')
        
        # Se não tiver um prompt personalizado e parecer um cronograma, sugerir um prompt específico
        is_schedule_analysis = False
        if 'cronograma' in image_file.filename.lower() or 'horario' in image_file.filename.lower() or 'grade' in image_file.filename.lower():
            is_schedule_analysis = True
            if not custom_prompt:
                custom_prompt = """
                Analise esta imagem de um cronograma escolar e extraia todas as informações em formato estruturado.
                Liste cada aula, incluindo:
                - Nome da matéria/disciplina
                - Dia da semana
                - Horário de início e fim
                - Nome do professor (se disponível)
                """
        
        # Analisar a imagem
        logger.info(f"Analisando imagem: {image_file.filename}")
        result = image_analyzer.analyze_image(image_file, custom_prompt)
        
        # Verificar se o resultado parece um cronograma (se ainda não foi identificado pelo nome do arquivo)
        if not is_schedule_analysis:
            # Palavras-chave que indicam que a análise é de um cronograma
            schedule_keywords = [
                'horário', 'cronograma', 'aula', 'matéria', 'disciplina', 
                'professor', 'escola', 'faculdade', 'universidade', 
                'turma', 'segunda', 'terça', 'quarta', 'quinta', 'sexta',
                'manhã', 'tarde', 'noite', 'semestre', 'semana', 'período'
            ]
            
            # Verificar a presença de palavras-chave
            if any(keyword in result.lower() for keyword in schedule_keywords):
                # Verificar se há menções a dias da semana e horários
                days = ['segunda', 'terça', 'quarta', 'quinta', 'sexta', 'sábado', 'domingo', 'seg', 'ter', 'qua', 'qui', 'sex']
                # Procurar padrões de horário comuns (8h, 14:30, etc.)
                import re
                times = re.findall(r'\d{1,2}[h:]\d{0,2}', result)
                
                if (any(day in result.lower() for day in days) and times):
                    is_schedule_analysis = True
        
        return jsonify({
            "success": True,
            "result": result,
            "is_schedule": is_schedule_analysis  # Indica se parece ser um cronograma
        })
        
    except Exception as e:
        logger.error(f"Erro na análise de imagem: {str(e)}")
        logger.exception("Detalhes do erro:")
        return jsonify({
            "success": False,
            "error": f"Erro ao processar a imagem: {str(e)}"
        })

# Rota para upload de cronograma para o Google Calendar
@app.route('/schedule_photo')
def schedule_photo_page():
    """Página para fazer upload de foto do cronograma e exportar para o Google Calendar"""
    return render_template('schedule_photo.html')

@app.route('/process_schedule_photo', methods=['POST'])
def process_schedule_photo():
    """Processar a foto do cronograma e gerar um ID para integração com Make.com"""
    try:
        # Verificar se uma imagem foi enviada
        if 'image' not in request.files:
            return jsonify({
                "success": False,
                "error": "Nenhuma imagem enviada."
            })
        
        image_file = request.files['image']
        
        # Verificar se o arquivo é válido
        if image_file.filename == '':
            return jsonify({
                "success": False,
                "error": "Arquivo de imagem inválido."
            })
            
        # Verificar extensão do arquivo
        allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
        if '.' not in image_file.filename or image_file.filename.rsplit('.', 1)[1].lower() not in allowed_extensions:
            return jsonify({
                "success": False,
                "error": "Formato de arquivo não suportado. Use PNG, JPG, JPEG, GIF ou WEBP."
            })
        
        # Usar o mesmo processo da funcionalidade "Salvar como Cronograma"
        # para analisar a imagem e extrair as informações
        prompt = """
        Analise esta imagem de um cronograma escolar e extraia todas as informações em formato estruturado.
        Liste cada aula, incluindo:
        - Nome da matéria/disciplina
        - Dia da semana
        - Horário de início e fim
        - Nome do professor (se disponível)
        """
        
        # Analisar a imagem
        logger.info(f"Analisando imagem de cronograma: {image_file.filename}")
        analysis_result = image_analyzer.analyze_image(image_file, prompt)
        
        if not analysis_result:
            return jsonify({
                "success": False,
                "error": "Não foi possível analisar a imagem."
            })
        
        # Obter cronograma atual
        current_schedule = schedule_manager.get_schedule() or {}
        
        # Solicitar ao assistente que extraia as informações em formato estruturado
        extraction_prompt = f"""
        Extraia informações estruturadas deste texto que descreve um cronograma escolar.
        
        Texto: {analysis_result}
        
        Forneça apenas a lista de matérias no formato:
        - Nome da matéria
        - Carga horária semanal estimada (em horas)
        
        E uma lista de aulas no formato:
        - Matéria
        - Dia da semana (Seg, Ter, Qua, Qui, Sex, Sab, Dom)
        - Horário de início (HH:MM)
        - Horário de término (HH:MM)
        - Professor
        """
        
        try:
            structured_info = chat_assistant.get_chat_response(extraction_prompt)
            
            # Extrair matérias e aulas como na funcionalidade existente
            import re
            subject_pattern = r'[-•*]\s*([^()\n-]+)(?:\s*\(?\s*(\d+)\s*(?:horas|hrs?|h)\)?)?'
            subjects_found = re.findall(subject_pattern, structured_info)
            
            class_pattern = r'[-•*]\s*([^:\n-]+)[\s:]+([^\s,]+)[,\s]+(\d{1,2}:\d{2})(?:\s*-\s*(\d{1,2}:\d{2}))?(?:[,\s]+(?:Prof\w*[.:])?\s*([^\n]+))?'
            classes_found = re.findall(class_pattern, structured_info)
            
            # Preparar as matérias
            subjects = []
            for subject_name, hours in subjects_found:
                name = subject_name.strip()
                hours_per_week = int(hours) if hours else 2
                
                if not any(s.get('name') == name for s in subjects):
                    subjects.append({
                        "name": name,
                        "hours_per_week": hours_per_week
                    })
            
            # Adicionar matérias das aulas não listadas explicitamente
            for class_subject, _, _, _, _ in classes_found:
                name = class_subject.strip()
                if name and not any(s.get('name') == name for s in subjects):
                    subjects.append({
                        "name": name,
                        "hours_per_week": 2  # Valor padrão
                    })
            
            # Preparar as aulas
            classes = []
            days_map = {
                'segunda': 'Seg', 'seg': 'Seg', 
                'terça': 'Ter', 'ter': 'Ter',
                'quarta': 'Qua', 'qua': 'Qua',
                'quinta': 'Qui', 'qui': 'Qui',
                'sexta': 'Sex', 'sex': 'Sex',
                'sábado': 'Sab', 'sab': 'Sab',
                'domingo': 'Dom', 'dom': 'Dom'
            }
            
            for class_subject, day, start_time, end_time, teacher in classes_found:
                # Normalizar o dia da semana
                day_code = day.strip().lower()
                day_code = days_map.get(day_code, day_code.capitalize()[:3])
                
                # Garantir que é um código de dia válido
                if day_code not in ["Seg", "Ter", "Qua", "Qui", "Sex", "Sab", "Dom"]:
                    continue
                    
                classes.append({
                    "subject": class_subject.strip(),
                    "day": day_code,
                    "start_time": start_time.strip(),
                    "end_time": end_time.strip() if end_time else "",
                    "teacher": teacher.strip() if teacher else ""
                })
                
            # Criar um identificador único para este cronograma
            import uuid
            import json
            from datetime import datetime
            
            schedule_id = str(uuid.uuid4())[:8]
            
            # Criar um objeto de exportação para o Make.com
            export_data = {
                "id": schedule_id,
                "created_at": datetime.now().isoformat(),
                "subjects": subjects,
                "classes": classes
            }
            
            # Salvar este objeto para uso posterior (integração com Make.com)
            export_dir = os.path.join('data', 'exports')
            os.makedirs(export_dir, exist_ok=True)
            
            with open(os.path.join(export_dir, f"schedule_{schedule_id}.json"), 'w') as f:
                json.dump(export_data, f, indent=2)
            
            # Também atualizar o cronograma local
            current_schedule['subjects'] = subjects
            
            if 'classes' not in current_schedule:
                current_schedule['classes'] = []
                
            for new_class in classes:
                if not any(c.get('day') == new_class.get('day') and 
                          c.get('start_time') == new_class.get('start_time') 
                          for c in current_schedule['classes']):
                    current_schedule['classes'].append(new_class)
            
            # Salvar o cronograma local
            schedule_manager.save_schedule()
            
            # Retornar o ID para o frontend usar na integração com Make.com
            return jsonify({
                "success": True,
                "schedule_id": schedule_id,
                "subjects_count": len(subjects),
                "classes_count": len(classes)
            })
            
        except Exception as extract_error:
            logger.error(f"Erro ao extrair informações do texto: {str(extract_error)}")
            logger.exception("Detalhes do erro:")
            return jsonify({
                "success": False,
                "error": "Não foi possível extrair informações do cronograma"
            }), 500
            
    except Exception as e:
        logger.error(f"Erro ao processar o cronograma: {str(e)}")
        logger.exception("Detalhes do erro:")
        return jsonify({
            "success": False,
            "error": f"Erro ao processar o cronograma: {str(e)}"
        }), 500

# Endpoint para o Make.com obter os dados do cronograma
@app.route('/api/schedule/export', methods=['GET'])
def api_export_schedule():
    """API para o Make.com obter os dados do cronograma"""
    try:
        schedule_id = request.args.get('id')
        
        if not schedule_id:
            return jsonify({
                "success": False,
                "error": "ID do cronograma não fornecido"
            }), 400
            
        # Carregar o arquivo de exportação
        export_path = os.path.join('data', 'exports', f"schedule_{schedule_id}.json")
        
        if not os.path.exists(export_path):
            return jsonify({
                "success": False,
                "error": "Cronograma não encontrado"
            }), 404
            
        with open(export_path, 'r') as f:
            export_data = json.load(f)
            
        # Formatar os dados para o Google Calendar
        calendar_events = []
        
        for cls in export_data.get('classes', []):
            subject = cls.get('subject', 'Aula')
            day = cls.get('day', '')
            start_time = cls.get('start_time', '')
            end_time = cls.get('end_time', '')
            teacher = cls.get('teacher', '')
            
            # Converter dias da semana para números (Make.com/Google Calendar)
            day_number = {
                'Seg': 1, 'Ter': 2, 'Qua': 3, 'Qui': 4, 'Sex': 5, 'Sab': 6, 'Dom': 0
            }.get(day, 1)  # Default para Segunda se não encontrar
            
            # Calcular duração se não tiver horário de fim
            if not end_time and start_time:
                # Presumir que a aula dura 50 minutos
                import datetime
                start_dt = datetime.datetime.strptime(start_time, '%H:%M')
                end_dt = start_dt + datetime.timedelta(minutes=50)
                end_time = end_dt.strftime('%H:%M')
            
            # Criar evento
            event = {
                "summary": subject,
                "description": f"Professor: {teacher}" if teacher else "",
                "day_of_week": day_number,
                "start_time": start_time,
                "end_time": end_time
            }
            
            calendar_events.append(event)
            
        return jsonify({
            "success": True,
            "events": calendar_events
        })
        
    except Exception as e:
        logger.error(f"Erro ao exportar cronograma: {str(e)}")
        logger.exception("Detalhes do erro:")
        return jsonify({
            "success": False,
            "error": f"Erro ao exportar cronograma: {str(e)}"
        }), 500

@app.route('/assistant_chat_image', methods=['POST'])
def process_chat_image():
    """Processar imagem de cronograma enviada pelo chat"""
    try:
        # Verificar se a mensagem e a imagem foram enviadas
        if 'message' not in request.form or 'image' not in request.files:
            return jsonify({'error': 'Mensagem ou imagem não fornecida'}), 400
        
        user_message = request.form.get('message')
        image_file = request.files.get('image')
        
        if not image_file or image_file.filename == '':
            return jsonify({'error': 'Imagem inválida'}), 400
            
        # Extrair o histórico do chat da sessão ou inicializar
        chat_history = session.get('chat_history', [])
        
        # Adicionar a mensagem do usuário ao histórico
        chat_history.append({"role": "user", "content": user_message})
        
        # Usar prompt específico para cronogramas
        prompt = """
        Analise esta imagem de um cronograma escolar e extraia todas as informações em formato estruturado.
        Liste cada aula, incluindo:
        - Nome da matéria/disciplina
        - Dia da semana
        - Horário de início e fim
        - Nome do professor (se disponível)
        """
        
        # Analisar a imagem
        logger.info(f"Analisando imagem de cronograma do chat: {image_file.filename}")
        analysis_result = image_analyzer.analyze_image(image_file, prompt)
        
        if not analysis_result:
            response = "Não consegui analisar a imagem do cronograma. Por favor, tente novamente com uma imagem mais clara."
            chat_history.append({"role": "assistant", "content": response})
            session['chat_history'] = chat_history
            return jsonify({'response': response})
        
        # Extrair informações estruturadas do texto da análise
        extraction_prompt = f"""
        Extraia informações estruturadas deste texto que descreve um cronograma escolar.
        
        Texto: {analysis_result}
        
        Forneça apenas a lista de matérias no formato:
        - Nome da matéria
        - Carga horária semanal estimada (em horas)
        
        E uma lista de aulas no formato:
        - Matéria
        - Dia da semana (Seg, Ter, Qua, Qui, Sex, Sab, Dom)
        - Horário de início (HH:MM)
        - Horário de término (HH:MM)
        - Professor
        """
        
        try:
            structured_info = chat_assistant.get_chat_response(extraction_prompt)
            
            # Extrair matérias e aulas como na funcionalidade existente
            import re
            subject_pattern = r'[-•*]\s*([^()\n-]+)(?:\s*\(?\s*(\d+)\s*(?:horas|hrs?|h)\)?)?'
            subjects_found = re.findall(subject_pattern, structured_info)
            
            class_pattern = r'[-•*]\s*([^:\n-]+)[\s:]+([^\s,]+)[,\s]+(\d{1,2}:\d{2})(?:\s*-\s*(\d{1,2}:\d{2}))?(?:[,\s]+(?:Prof\w*[.:])?\s*([^\n]+))?'
            classes_found = re.findall(class_pattern, structured_info)
            
            # Preparar as matérias
            subjects = []
            for subject_name, hours in subjects_found:
                name = subject_name.strip()
                hours_per_week = int(hours) if hours else 2
                
                if not any(s.get('name') == name for s in subjects):
                    subjects.append({
                        "name": name,
                        "hours_per_week": hours_per_week
                    })
            
            # Adicionar matérias das aulas não listadas explicitamente
            for class_subject, _, _, _, _ in classes_found:
                name = class_subject.strip()
                if name and not any(s.get('name') == name for s in subjects):
                    subjects.append({
                        "name": name,
                        "hours_per_week": 2  # Valor padrão
                    })
            
            # Preparar as aulas
            classes = []
            days_map = {
                'segunda': 'Seg', 'seg': 'Seg', 
                'terça': 'Ter', 'ter': 'Ter',
                'quarta': 'Qua', 'qua': 'Qua',
                'quinta': 'Qui', 'qui': 'Qui',
                'sexta': 'Sex', 'sex': 'Sex',
                'sábado': 'Sab', 'sab': 'Sab',
                'domingo': 'Dom', 'dom': 'Dom'
            }
            
            for class_subject, day, start_time, end_time, teacher in classes_found:
                # Normalizar o dia da semana
                day_code = day.strip().lower()
                day_code = days_map.get(day_code, day_code.capitalize()[:3])
                
                # Garantir que é um código de dia válido
                if day_code not in ["Seg", "Ter", "Qua", "Qui", "Sex", "Sab", "Dom"]:
                    continue
                    
                classes.append({
                    "subject": class_subject.strip(),
                    "day": day_code,
                    "start_time": start_time.strip(),
                    "end_time": end_time.strip() if end_time else "",
                    "teacher": teacher.strip() if teacher else ""
                })
            
            # Carregar o cronograma atual
            current_schedule = schedule_manager.get_schedule() or {}
            
            # Atualizar o cronograma
            current_schedule['subjects'] = subjects
            
            if 'classes' not in current_schedule:
                current_schedule['classes'] = []
                
            for new_class in classes:
                if not any(c.get('day') == new_class.get('day') and 
                          c.get('start_time') == new_class.get('start_time') 
                          for c in current_schedule['classes']):
                    current_schedule['classes'].append(new_class)
            
            # Salvar o cronograma atualizado
            schedule_manager.save_schedule()
            
            # Gerar uma resposta personalizada
            num_subjects = len(subjects)
            num_classes = len(classes)
            
            response = f"""✅ **Cronograma identificado e salvo com sucesso!**

Identifiquei {num_subjects} matérias e {num_classes} aulas no seu cronograma.

O cronograma foi automaticamente adicionado à sua aba de Cronograma. Você pode visualizá-lo clicando no menu "Ver Cronograma".

**Matérias identificadas:**
"""
            
            for subject in subjects:
                response += f"- {subject['name']} ({subject['hours_per_week']} horas/semana)\n"
                
            response += "\n**Algumas aulas identificadas:**\n"
            
            # Mostrar até 5 aulas como exemplo
            for i, cls in enumerate(classes[:5]):
                teacher_info = f", Prof. {cls['teacher']}" if cls['teacher'] else ""
                time_info = f"{cls['start_time']}"
                if cls['end_time']:
                    time_info += f" - {cls['end_time']}"
                
                response += f"- {cls['subject']} ({cls['day']}, {time_info}{teacher_info})\n"
                
            if len(classes) > 5:
                response += f"- ... e mais {len(classes) - 5} aulas\n"
                
            response += "\nPosso ajudar você a gerenciar esse cronograma ou responder perguntas sobre ele, como 'Quais aulas tenho na segunda-feira?' ou 'Qual é meu professor de matemática?'"
            
            # Adicionar a resposta ao histórico
            chat_history.append({"role": "assistant", "content": response})
            
            # Manter apenas as últimas 10 interações (20 mensagens)
            if len(chat_history) > 20:
                chat_history = chat_history[-20:]
                
            # Salvar o histórico atualizado na sessão
            session['chat_history'] = chat_history
            
            return jsonify({'response': response})
            
        except Exception as extract_error:
            logger.error(f"Erro ao extrair informações do texto: {str(extract_error)}")
            logger.exception("Detalhes do erro:")
            
            # Resposta de fallback em caso de erro na extração
            fallback_response = f"Analisei a imagem do seu cronograma, mas tive dificuldades para estruturar os dados. Aqui está o que consegui identificar:\n\n{analysis_result}\n\nVocê poderia me pedir para adicionar as aulas manualmente?"
            
            chat_history.append({"role": "assistant", "content": fallback_response})
            
            # Manter apenas as últimas 10 interações (20 mensagens)
            if len(chat_history) > 20:
                chat_history = chat_history[-20:]
                
            # Salvar o histórico atualizado na sessão
            session['chat_history'] = chat_history
            
            return jsonify({'response': fallback_response})
            
    except Exception as e:
        logger.error(f"Erro ao processar imagem do chat: {str(e)}")
        logger.exception("Detalhes do erro:")
        return jsonify({'error': str(e)}), 500

# Rotas para integração com Google Calendar
@app.route('/oauth_diagnosis')
def oauth_diagnosis():
    """Página de diagnóstico da configuração OAuth"""
    if not g.user:
        flash("Você precisa estar logado para acessar esta página", "warning")
        return redirect(url_for('login'))
    
    # Coletar informações de diagnóstico
    # Obtém o domínio do Replit
    replit_domain = os.environ.get('REPLIT_DOMAINS', 'Não definido')
    
    # Define a URL de callback usada na autenticação
    callback_url = f"https://{replit_domain}/google_calendar/callback"
    
    oauth_info = {
        'replit_domain': replit_domain,
        'redirect_uri': callback_url,
        'client_id_configured': bool(os.environ.get('GOOGLE_OAUTH_CLIENT_ID')),
        'client_secret_configured': bool(os.environ.get('GOOGLE_OAUTH_CLIENT_SECRET')),
        'callback_path': '/google_calendar/callback',
        'full_callback_url': callback_url,
        'user_id': g.user.user_id if g.user else None,
        'has_tokens': False
    }
    
    # Verificar se existem tokens salvos
    token_path = Path(f'data/tokens/{g.user.user_id}.json')
    if token_path.exists():
        oauth_info['has_tokens'] = True
        oauth_info['token_size'] = token_path.stat().st_size
        oauth_info['token_modified'] = datetime.datetime.fromtimestamp(
            token_path.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')
    
    return render_template('oauth_diagnosis.html', oauth_info=oauth_info)

@app.route('/export_calendar')
def export_calendar_page():
    """Página para exportar cronograma para o Google Calendar"""
    if not g.user:
        flash("Você precisa estar logado para exportar seu cronograma", "warning")
        return redirect(url_for('login'))
    
    # Carregar dados do cronograma
    schedule_data = schedule_manager.get_schedule()
    
    # Verificar se o cronograma tem aulas
    has_classes = False
    if schedule_data and 'classes' in schedule_data and len(schedule_data['classes']) > 0:
        has_classes = True
    
    # Inicializar o gerenciador do Google Calendar
    calendar_manager = GoogleCalendarManager(g.user.user_id)
    
    # Verificar se o usuário já está autorizado
    is_authorized = calendar_manager.is_authorized()
    
    # Se não estiver autorizado, gerar URL de autorização
    auth_url = None
    if not is_authorized:
        auth_url, state = calendar_manager.get_authorization_url()
        if auth_url:
            # Armazenar o estado na sessão para validação posterior
            session['oauth_state'] = state
        else:
            flash("Não foi possível gerar o link de autorização. Tente novamente mais tarde.", "danger")
    
    # Obter dados do cronograma
    schedule_data = schedule_manager.get_schedule()
    
    # Obter informações OAuth para o template
    replit_domain = os.environ.get('REPLIT_DOMAINS', 'Não definido')
    callback_url = f"https://{replit_domain}/google_calendar/callback"
    oauth_info = {
        'replit_domain': replit_domain,
        'full_callback_url': callback_url,
    }
    
    return render_template('export_calendar.html', 
                          is_authorized=is_authorized,
                          auth_url=auth_url,
                          schedule_data=schedule_data,
                          oauth_info=oauth_info)

@app.route('/google_calendar/callback')
def google_auth_callback():
    """Callback para autorização do Google Calendar"""
    if not g.user:
        flash("Você precisa estar logado para concluir a autorização", "warning")
        return redirect(url_for('login'))
    
    # Obter código de autorização da URL
    authorization_response = request.url
    state = request.args.get('state')
    
    # Verificar o estado para prevenção de ataques CSRF
    if state != session.get('oauth_state'):
        flash("Erro de validação de estado. Tente novamente.", "danger")
        return redirect(url_for('export_calendar_page'))
    
    # Trocar o código por tokens de acesso
    calendar_manager = GoogleCalendarManager(g.user.user_id)
    success = calendar_manager.handle_oauth_callback(authorization_response, state)
    
    if success:
        flash("Autorização concluída com sucesso! Você agora pode exportar seu cronograma para o Google Calendar.", "success")
    else:
        flash("Erro ao concluir autorização. Por favor, tente novamente.", "danger")
    
    return redirect(url_for('export_calendar_page'))

@app.route('/export_to_google_calendar', methods=['POST'])
def export_to_google_calendar():
    """Exportar cronograma para o Google Calendar"""
    if not g.user:
        flash("Você precisa estar logado para exportar seu cronograma", "warning")
        return redirect(url_for('login'))
    
    # Obter dados do cronograma
    schedule_data = schedule_manager.get_schedule()
    
    # Verificar se há aulas no cronograma
    if not schedule_data or 'classes' not in schedule_data or not schedule_data['classes']:
        flash("Nenhuma aula encontrada no cronograma. Adicione aulas antes de exportar.", "warning")
        return redirect(url_for('export_calendar_page'))
    
    # Inicializar o gerenciador do Google Calendar
    calendar_manager = GoogleCalendarManager(g.user.user_id)
    
    # Verificar se o usuário está autorizado
    if not calendar_manager.is_authorized():
        flash("Você precisa autorizar o Estudix a acessar seu Google Calendar primeiro.", "warning")
        return redirect(url_for('export_calendar_page'))
    
    # Criar eventos no Google Calendar
    result = calendar_manager.create_calendar_events_from_schedule(schedule_data)
    
    if result['success']:
        flash(result['message'], "success")
    else:
        flash(f"Erro ao exportar cronograma: {result.get('error', 'Erro desconhecido')}", "danger")
    
    return redirect(url_for('export_calendar_page'))

@app.route('/revoke_google_access')
def revoke_google_access():
    """Revogar acesso ao Google Calendar"""
    if not g.user:
        flash("Você precisa estar logado para gerenciar suas integrações", "warning")
        return redirect(url_for('login'))
    
    # Inicializar o gerenciador do Google Calendar
    calendar_manager = GoogleCalendarManager(g.user.user_id)
    
    # Revogar acesso
    success = calendar_manager.revoke_access()
    
    if success:
        flash("Acesso ao Google Calendar revogado com sucesso.", "success")
    else:
        flash("Erro ao revogar acesso. Tente novamente mais tarde.", "danger")
    
    return redirect(url_for('export_calendar_page'))

@app.route('/export_ical')
def export_ical():
    """Exportar cronograma para formato iCalendar (.ics)"""
    if not g.user:
        flash("Você precisa estar logado para exportar seu cronograma", "warning")
        return redirect(url_for('login'))
    
    # Obter dados do cronograma
    schedule_data = schedule_manager.get_schedule()
    
    # Verificar se há aulas no cronograma
    if not schedule_data or 'classes' not in schedule_data or not schedule_data['classes']:
        flash("Nenhuma aula encontrada no cronograma. Adicione aulas antes de exportar.", "warning")
        return redirect(url_for('export_calendar_page'))
    
    # Gerar arquivo iCalendar
    ics_file_path = ical_exporter.generate_ical(schedule_data)
    
    if not ics_file_path:
        flash("Erro ao gerar arquivo iCalendar. Tente novamente mais tarde.", "danger")
        return redirect(url_for('export_calendar_page'))
    
    # Enviar o arquivo para download
    try:
        return send_file(ics_file_path, 
                        as_attachment=True,
                        download_name=f"estudix_cronograma_{datetime.datetime.now().strftime('%Y%m%d')}.ics",
                        mimetype="text/calendar")
    except Exception as e:
        logger.error(f"Erro ao enviar arquivo iCalendar: {e}")
        flash("Erro ao enviar arquivo para download. Tente novamente mais tarde.", "danger")
        return redirect(url_for('export_calendar_page'))

if __name__ == "__main__":
    # Configurar a chave da API do Google
    os.environ['GOOGLE_API_KEY'] = "AIzaSyCYIfgQ023pbwiyGZegekT7xxWyHuBSbyk"
    app.run(host="0.0.0.0", port=5000, debug=True)
