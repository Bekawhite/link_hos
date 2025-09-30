import streamlit as st
import hashlib
import sqlalchemy as db
from sqlalchemy import create_engine, Column, String, Integer, DateTime, JSON, Text, Boolean, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from datetime import datetime, timedelta
import pandas as pd
import plotly.express as px
import pydeck as pdk
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import numpy as np
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch
import secrets
import string
from dotenv import load_dotenv
import time
import threading

load_dotenv()

# =============================================================================
# CONFIGURATION
# =============================================================================
class Config:
    DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///hospital_referral.db')
    SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
    SMTP_PORT = int(os.getenv('SMTP_PORT', 587))
    SMTP_USERNAME = os.getenv('SMTP_USERNAME')
    SMTP_PASSWORD = os.getenv('SMTP_PASSWORD')
    DEFAULT_LATITUDE = -0.0916
    DEFAULT_LONGITUDE = 34.7680
    DEFAULT_ZOOM = 10
    PAGE_TITLE = "Kisumu County Hospital Referral System"
    PAGE_ICON = "🏥"
    LAYOUT = "wide"
    GOOGLE_MAPS_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY', '')

# =============================================================================
# DATABASE MODELS
# =============================================================================
Base = declarative_base()

class Patient(Base):
    __tablename__ = 'patients'
    patient_id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    age = Column(Integer, nullable=False)
    condition = Column(String, nullable=False)
    referring_hospital = Column(String, nullable=False)
    receiving_hospital = Column(String, nullable=False)
    referring_physician = Column(String, nullable=False)
    receiving_physician = Column(String)
    notes = Column(Text)
    vital_signs = Column(JSON)
    medical_history = Column(Text)
    current_medications = Column(Text)
    allergies = Column(Text)
    referral_time = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default='Referred')
    assigned_ambulance = Column(String)
    created_by = Column(String)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    referring_hospital_lat = Column(Float)
    referring_hospital_lng = Column(Float)
    receiving_hospital_lat = Column(Float)
    receiving_hospital_lng = Column(Float)

class Ambulance(Base):
    __tablename__ = 'ambulances'
    ambulance_id = Column(String, primary_key=True)
    current_location = Column(String)
    latitude = Column(Float)
    longitude = Column(Float)
    status = Column(String, default='Available')
    driver_name = Column(String)
    driver_contact = Column(String)
    current_patient = Column(String)
    destination = Column(String)
    route = Column(JSON)
    start_time = Column(DateTime)
    current_step = Column(Integer, default=0)
    mission_complete = Column(Boolean, default=False)
    estimated_arrival = Column(DateTime)
    last_location_update = Column(DateTime, default=datetime.utcnow)

class Referral(Base):
    __tablename__ = 'referrals'
    id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(String, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default='Ambulance Dispatched')
    ambulance_id = Column(String)
    created_by = Column(String)

class HandoverForm(Base):
    __tablename__ = 'handover_forms'
    id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(String, nullable=False)
    patient_name = Column(String)
    age = Column(Integer)
    condition = Column(String)
    referring_hospital = Column(String)
    receiving_hospital = Column(String)
    referring_physician = Column(String)
    receiving_physician = Column(String)
    transfer_time = Column(DateTime, default=datetime.utcnow)
    vital_signs = Column(JSON)
    medical_history = Column(Text)
    current_medications = Column(Text)
    allergies = Column(Text)
    notes = Column(Text)
    ambulance_id = Column(String)
    created_by = Column(String)

class Communication(Base):
    __tablename__ = 'communications'
    id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(String)
    ambulance_id = Column(String)
    sender = Column(String)
    receiver = Column(String)
    message = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)
    message_type = Column(String)  # 'driver_hospital', 'hospital_hospital', 'system'

class LocationUpdate(Base):
    __tablename__ = 'location_updates'
    id = Column(Integer, primary_key=True, autoincrement=True)
    ambulance_id = Column(String)
    latitude = Column(Float)
    longitude = Column(Float)
    location_name = Column(String)
    timestamp = Column(DateTime, default=datetime.utcnow)
    patient_id = Column(String)

# =============================================================================
# DATABASE SERVICE
# =============================================================================
class Database:
    def __init__(self):
        if os.getenv('DATABASE_URL'):
            self.engine = create_engine(os.getenv('DATABASE_URL'))
        else:
            self.engine = create_engine('sqlite:///hospital_referral.db')
        Base.metadata.create_all(self.engine)
        Session = sessionmaker(bind=self.engine)
        self.session = Session()
    
    def add_patient(self, patient_data):
        # Generate patient ID if not provided
        if 'patient_id' not in patient_data:
            patient_data['patient_id'] = f"PAT{secrets.token_hex(4).upper()}"
        
        patient = Patient(**patient_data)
        self.session.add(patient)
        self.session.commit()
        return patient
    
    def get_available_ambulances(self):
        return self.session.query(Ambulance).filter(Ambulance.status == 'Available').all()
    
    def update_ambulance_status(self, ambulance_id, status, patient_id=None):
        ambulance = self.session.query(Ambulance).filter(Ambulance.ambulance_id == ambulance_id).first()
        if ambulance:
            ambulance.status = status
            if patient_id:
                ambulance.current_patient = patient_id
            self.session.commit()
    
    def get_patient_by_id(self, patient_id):
        return self.session.query(Patient).filter(Patient.patient_id == patient_id).first()
    
    def get_all_patients(self):
        return self.session.query(Patient).all()
    
    def get_all_ambulances(self):
        return self.session.query(Ambulance).all()
    
    def add_referral(self, referral_data):
        referral = Referral(**referral_data)
        self.session.add(referral)
        self.session.commit()
        return referral
    
    def add_handover_form(self, handover_data):
        handover = HandoverForm(**handover_data)
        self.session.add(handover)
        self.session.commit()
        return handover
    
    def add_communication(self, communication_data):
        communication = Communication(**communication_data)
        self.session.add(communication)
        self.session.commit()
        return communication
    
    def get_communications_for_patient(self, patient_id):
        return self.session.query(Communication).filter(Communication.patient_id == patient_id).order_by(Communication.timestamp.desc()).all()
    
    def get_communications_for_ambulance(self, ambulance_id):
        return self.session.query(Communication).filter(Communication.ambulance_id == ambulance_id).order_by(Communication.timestamp.desc()).all()
    
    def add_location_update(self, location_data):
        location_update = LocationUpdate(**location_data)
        self.session.add(location_update)
        self.session.commit()
        return location_update
    
    def get_latest_location(self, ambulance_id):
        return self.session.query(LocationUpdate).filter(
            LocationUpdate.ambulance_id == ambulance_id
        ).order_by(LocationUpdate.timestamp.desc()).first()

# =============================================================================
# AUTHENTICATION
# =============================================================================
class Authentication:
    def __init__(self):
        self.credentials = {
            'usernames': {
                'admin': {
                    'password': self._hash_password('admin123'),
                    'email': 'admin@kisumu.gov',
                    'role': 'Admin',
                    'hospital': 'All Facilities',
                    'name': 'System Administrator'
                },
                'hospital_staff': {
                    'password': self._hash_password('staff123'),
                    'email': 'staff@joortrh.go.ke',
                    'role': 'Hospital Staff',
                    'hospital': 'Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)',
                    'name': 'Hospital Staff Member'
                },
                'driver': {
                    'password': self._hash_password('driver123'),
                    'email': 'driver@kisumu.gov',
                    'role': 'Ambulance Driver',
                    'hospital': 'Ambulance Service',
                    'name': 'Ambulance Driver'
                },
                'kisumu_staff': {
                    'password': self._hash_password('kisumu123'),
                    'email': 'staff@kisumuhospital.go.ke',
                    'role': 'Hospital Staff',
                    'hospital': 'Kisumu County Referral Hospital',
                    'name': 'Kisumu County Hospital Staff'
                }
            }
        }
    
    def _hash_password(self, password):
        return hashlib.sha256(password.encode()).hexdigest()
    
    def authenticate_user(self, username, password):
        if username in self.credentials['usernames']:
            stored_password = self.credentials['usernames'][username]['password']
            if self._hash_password(password) == stored_password:
                return self.credentials['usernames'][username]
        return None
    
    def setup_auth_ui(self):
        st.sidebar.title("🔐 Login")
        username = st.sidebar.text_input("Username")
        password = st.sidebar.text_input("Password", type="password")
        
        if st.sidebar.button("Login", use_container_width=True):
            user = self.authenticate_user(username, password)
            if user:
                st.session_state.user = user
                st.session_state.authenticated = True
                st.sidebar.success(f"Welcome {user['role']}!")
                st.rerun()
            else:
                st.sidebar.error("Invalid credentials")
        
        if st.session_state.get('authenticated'):
            if st.sidebar.button("Logout", use_container_width=True):
                st.session_state.clear()
                st.rerun()
    
    def require_auth(self, roles=None):
        if not st.session_state.get('authenticated'):
            st.warning("Please login to access this page")
            return False
        if roles and st.session_state.user['role'] not in roles:
            st.error(f"Access denied. Required roles: {', '.join(roles)}")
            return False
        return True

# =============================================================================
# SERVICES
# =============================================================================
class AnalyticsService:
    def __init__(self, db):
        self.db = db
    
    def get_kpis(self):
        patients = self.db.get_all_patients()
        ambulances = self.db.get_all_ambulances()
        total_referrals = len(patients)
        active_referrals = len([p for p in patients if p.status not in ['Arrived at Destination', 'Completed']])
        available_ambulances = len([a for a in ambulances if a.status == 'Available'])
        response_times = []
        for patient in patients:
            if patient.assigned_ambulance and patient.status == 'Arrived at Destination':
                response_times.append(15)
        avg_response_time = sum(response_times) / len(response_times) if response_times else 0
        return {
            'total_referrals': total_referrals,
            'active_referrals': active_referrals,
            'available_ambulances': available_ambulances,
            'avg_response_time': f"{avg_response_time:.1f} min",
            'completion_rate': f"{(total_referrals - active_referrals) / total_referrals * 100:.1f}%" if total_referrals > 0 else "0%"
        }
    
    def get_referral_trends(self):
        patients = self.db.get_all_patients()
        df = pd.DataFrame([{
            'date': p.referral_time.date(),
            'condition': p.condition,
            'hospital': p.referring_hospital
        } for p in patients])
        if not df.empty:
            trends = df.groupby('date').size().reset_index(name='count')
            return trends
        return pd.DataFrame()
    
    def get_hospital_stats(self):
        patients = self.db.get_all_patients()
        df = pd.DataFrame([{
            'hospital': p.referring_hospital,
            'status': p.status
        } for p in patients])
        if not df.empty:
            stats = df.groupby(['hospital', 'status']).size().reset_index(name='count')
            return stats
        return pd.DataFrame()

class NotificationService:
    def __init__(self):
        pass  # Removed Twilio dependency
    
    def send_sms(self, to_number, message):
        st.warning("SMS notifications not configured (Twilio not available)")
        return False
    
    def send_email(self, to_email, subject, message):
        try:
            smtp_server = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
            smtp_port = int(os.getenv('SMTP_PORT', 587))
            smtp_username = os.getenv('SMTP_USERNAME')
            smtp_password = os.getenv('SMTP_PASSWORD')
            
            if not smtp_username or not smtp_password:
                st.warning("Email configuration not complete")
                return False
                
            msg = MIMEMultipart()
            msg['From'] = smtp_username
            msg['To'] = to_email
            msg['Subject'] = subject
            msg.attach(MIMEText(message, 'plain'))
            
            server = smtplib.SMTP(smtp_server, smtp_port)
            server.starttls()
            server.login(smtp_username, smtp_password)
            server.send_message(msg)
            server.quit()
            return True
        except Exception as e:
            st.error(f"Failed to send email: {e}")
            return False
    
    def send_notification(self, recipient, message, notification_type):
        if notification_type == 'referral':
            subject = "New Patient Referral"
        elif notification_type == 'dispatch':
            subject = "Ambulance Dispatched"
        elif notification_type == 'arrival':
            subject = "Patient Arrival Notification"
        else:
            subject = "Hospital Referral System Notification"
        
        st.success(f"📧 Notification prepared: {subject} - {message}")
        return True

class ReferralService:
    def __init__(self, db):
        self.db = db
    
    def create_referral(self, patient_data, user):
        try:
            patient_data['created_by'] = user['role']
            patient = self.db.add_patient(patient_data)
            referral_data = {
                'patient_id': patient.patient_id,
                'ambulance_id': patient_data.get('assigned_ambulance'),
                'created_by': user['role']
            }
            self.db.add_referral(referral_data)
            return patient
        except Exception as e:
            st.error(f"Error creating referral: {e}")
            return None
    
    def assign_ambulance(self, patient_id, ambulance_id):
        try:
            patient = self.db.get_patient_by_id(patient_id)
            if patient:
                patient.assigned_ambulance = ambulance_id
                patient.status = 'Ambulance Assigned'
                self.db.session.commit()
                self.db.update_ambulance_status(ambulance_id, 'On Transfer', patient_id)
                return True
        except Exception as e:
            st.error(f"Error assigning ambulance: {e}")
        return False

class AmbulanceService:
    def __init__(self, db):
        self.db = db
    
    def get_available_ambulances_df(self):
        ambulances = self.db.get_available_ambulances()
        data = []
        for ambulance in ambulances:
            data.append({
                'Ambulance ID': ambulance.ambulance_id,
                'Driver': ambulance.driver_name,
                'Contact': ambulance.driver_contact,
                'Location': ambulance.current_location,
                'Status': ambulance.status
            })
        return pd.DataFrame(data)
    
    def update_ambulance_location(self, ambulance_id, latitude, longitude, location_name, patient_id=None):
        try:
            ambulance = self.db.session.query(Ambulance).filter(
                Ambulance.ambulance_id == ambulance_id
            ).first()
            if ambulance:
                ambulance.latitude = latitude
                ambulance.longitude = longitude
                ambulance.current_location = location_name
                ambulance.last_location_update = datetime.utcnow()
                self.db.session.commit()
                
                # Add to location updates table
                location_data = {
                    'ambulance_id': ambulance_id,
                    'latitude': latitude,
                    'longitude': longitude,
                    'location_name': location_name,
                    'patient_id': patient_id
                }
                self.db.add_location_update(location_data)
                return True
        except Exception as e:
            st.error(f"Error updating ambulance location: {e}")
        return False

class LocationSimulator:
    def __init__(self, db):
        self.db = db
        self.running = False
    
    def start_simulation(self, ambulance_id, patient_id, start_lat, start_lng, end_lat, end_lng):
        self.running = True
        ambulance_service = AmbulanceService(self.db)
        
        # Simulate movement along a route
        current_lat, current_lng = start_lat, start_lng
        steps = 20
        lat_step = (end_lat - start_lat) / steps
        lng_step = (end_lng - start_lng) / steps
        
        for step in range(steps + 1):
            if not self.running:
                break
                
            current_lat = start_lat + (lat_step * step)
            current_lng = start_lng + (lng_step * step)
            
            # Update location in database
            ambulance_service.update_ambulance_location(
                ambulance_id, current_lat, current_lng, 
                f"En route - Step {step}/{steps}", patient_id
            )
            
            time.sleep(5)  # Update every 5 seconds
        
        # Mark as arrived
        if self.running:
            ambulance = self.db.session.query(Ambulance).filter(
                Ambulance.ambulance_id == ambulance_id
            ).first()
            if ambulance:
                ambulance.status = 'Available'
                ambulance.current_patient = None
                self.db.session.commit()
    
    def stop_simulation(self):
        self.running = False

# =============================================================================
# UTILITIES
# =============================================================================
class MapUtils:
    @staticmethod
    def create_uber_style_map(patient, ambulance, hospitals_df):
        """Create an Uber-style map showing ambulance, hospitals, and route"""
        if not ambulance or not patient:
            return None
        
        # Get hospital coordinates
        referring_hospital_data = hospitals_df[hospitals_df['facility_name'] == patient.referring_hospital].iloc[0]
        receiving_hospital_data = hospitals_df[hospitals_df['facility_name'] == patient.receiving_hospital].iloc[0]
        
        # Create layers
        hospitals_layer = pdk.Layer(
            'ScatterplotLayer',
            data=[
                {
                    'name': patient.referring_hospital,
                    'coordinates': [referring_hospital_data['longitude'], referring_hospital_data['latitude']],
                    'color': [0, 128, 0, 200],
                    'radius': 300
                },
                {
                    'name': patient.receiving_hospital,
                    'coordinates': [receiving_hospital_data['longitude'], receiving_hospital_data['latitude']],
                    'color': [255, 0, 0, 200],
                    'radius': 300
                }
            ],
            get_position='coordinates',
            get_color='color',
            get_radius='radius',
            pickable=True
        )
        
        ambulance_layer = pdk.Layer(
            'ScatterplotLayer',
            data=[{
                'name': f"Ambulance {ambulance.ambulance_id}",
                'coordinates': [ambulance.longitude, ambulance.latitude],
                'color': [0, 0, 255, 200],
                'radius': 200
            }],
            get_position='coordinates',
            get_color='color',
            get_radius='radius',
            pickable=True
        )
        
        # Create route line
        route_layer = pdk.Layer(
            'LineLayer',
            data=[{
                'path': [
                    [referring_hospital_data['longitude'], referring_hospital_data['latitude']],
                    [ambulance.longitude, ambulance.latitude],
                    [receiving_hospital_data['longitude'], receiving_hospital_data['latitude']]
                ],
                'color': [255, 165, 0, 150]
            }],
            get_path='path',
            get_color='color',
            get_width=5,
            pickable=True
        )
        
        # Calculate view state
        center_lat = (referring_hospital_data['latitude'] + receiving_hospital_data['latitude'] + ambulance.latitude) / 3
        center_lng = (referring_hospital_data['longitude'] + receiving_hospital_data['longitude'] + ambulance.longitude) / 3
        
        view_state = pdk.ViewState(
            latitude=center_lat,
            longitude=center_lng,
            zoom=11,
            pitch=0
        )
        
        return pdk.Deck(
            layers=[hospitals_layer, ambulance_layer, route_layer],
            initial_view_state=view_state,
            tooltip={
                'html': '<b>{name}</b>',
                'style': {'color': 'white'}
            }
        )

    @staticmethod
    def embed_google_maps(latitude, longitude, zoom=12):
        """Embed Google Maps with the specified coordinates"""
        if Config.GOOGLE_MAPS_API_KEY:
            return f"""
            <iframe
                width="100%"
                height="400"
                frameborder="0" style="border:0"
                src="https://www.google.com/maps/embed/v1/view?key={Config.GOOGLE_MAPS_API_KEY}&center={latitude},{longitude}&zoom={zoom}"
                allowfullscreen>
            </iframe>
            """
        else:
            return """
            <div style="background-color: #f0f0f0; padding: 20px; text-align: center;">
                <h3>Google Maps Integration</h3>
                <p>To enable Google Maps, please set the GOOGLE_MAPS_API_KEY environment variable.</p>
                <p>Current coordinates: {latitude}, {longitude}</p>
            </div>
            """

class PDFExporter:
    def __init__(self):
        self.styles = getSampleStyleSheet()
    
    def export_referral_form(self, patient, ambulance, output_path):
        doc = SimpleDocTemplate(output_path, pagesize=A4)
        story = []
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=self.styles['Heading1'],
            fontSize=16,
            spaceAfter=30,
            alignment=1
        )
        story.append(Paragraph("HOSPITAL PATIENT REFERRAL FORM", title_style))
        story.append(Spacer(1, 20))
        patient_data = [
            ['Patient Information', ''],
            ['Patient ID:', patient.patient_id],
            ['Name:', patient.name],
            ['Age:', str(patient.age)],
            ['Condition:', patient.condition],
            ['Referring Physician:', patient.referring_physician]
        ]
        patient_table = Table(patient_data, colWidths=[2*inch, 4*inch])
        patient_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        story.append(patient_table)
        story.append(Spacer(1, 20))
        doc.build(story)
        return output_path

class SecurityUtils:
    @staticmethod
    def generate_secure_password(length=12):
        alphabet = string.ascii_letters + string.digits + string.punctuation
        password = ''.join(secrets.choice(alphabet) for _ in range(length))
        return password
    
    @staticmethod
    def hash_password(password):
        return hashlib.sha256(password.encode()).hexdigest()
    
    @staticmethod
    def verify_password(password, hashed):
        return SecurityUtils.hash_password(password) == hashed

# =============================================================================
# DATA MODELS
# =============================================================================
hospitals_data = {
    'facility_name': [
        'Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)',
        'Kisumu County Referral Hospital', 'Lumumba Sub-County Hospital', 'Ahero Sub-County Hospital',
        'Kombewa Sub-County / District Hospital', 'Muhoroni County Hospital', 'Nyakach Sub-County Hospital',
        'Chulaimbo Sub-County Hospital', 'Masogo Sub-County (Sub-District) Hospital', 'Nyando District Hospital',
        'Ober Kamoth Sub-County Hospital', 'Rabuor Sub-County Hospital', 'Nyangoma Sub-County Hospital',
        'Nyahera Sub-County Hospital', 'Katito Sub-County Hospital', 'Gita Sub-County Hospital',
        'Masogo Health Centre', 'Victoria Hospital (public) Kisumu', 'Kodiaga Prison Health Centre',
        'Kisumu District Hospital', 'Migosi Health Centre', 'Katito Health Centre', 'Mbaka Oromo Health Centre',
        'Migere Health Centre', 'Milenye Health Centre', 'Minyange Dispensary', 'Nduru Kadero Health Centre',
        'Newa Dispensary', 'Nyakoko Dispensary', 'Ojola Sub-County Hospital', 'Simba Opepo Health Centre',
        'Songhor Health Centre', 'St Marks Lela Health Centre', 'Maseno University Health Centre',
        'Geta Health Centre', 'Kadinda Health Centre', 'Kochieng Health Centre', 'Kodingo Health Centre',
        'Kolenyo Health Centre', 'Kandu Health Centre'
    ],
    'latitude': [
        -0.0754, -0.0754, -0.1058, -0.1743, -0.1813, -0.1551, -0.2670, -0.1848, -0.1855, -0.3573,
        -0.3789, -0.2138, -0.1625, -0.1565, -0.4533, -0.3735, -0.1855, -0.0878, -0.0607, -0.0916,
        -0.1073, -0.4533, -0.2628, -0.1225, -0.1872, -0.2192, -0.1356, -0.2014, -0.2678, -0.1578,
        -0.3381, -0.2131, -0.0803, -0.0025, -0.4739, -0.2167, -0.3658, -0.0956, -0.4536, -0.2314
    ],
    'longitude': [
        34.7695, 34.7695, 34.7568, 34.9169, 34.6326, 35.1985, 35.0569, 34.6163, 35.0386, 35.0006,
        35.0299, 34.8817, 34.7794, 34.7508, 34.9561, 34.9676, 35.0386, 34.7686, 34.7509, 34.7647,
        34.7794, 34.9561, 34.6061, 34.7553, 34.7781, 34.8331, 34.7381, 34.8289, 34.9981, 34.8419,
        34.9456, 35.1611, 34.6569, 34.6053, 34.9519, 34.8419, 34.9606, 34.7658, 34.9564, 34.8489
    ],
    'facility_type': [
        'Referral Hospital', 'Referral Hospital', 'Sub-County Hospital', 'Sub-County Hospital',
        'Sub-County Hospital', 'County Hospital', 'Sub-County Hospital', 'Sub-County Hospital',
        'Sub-County Hospital', 'District Hospital', 'Sub-County Hospital', 'Sub-County Hospital',
        'Sub-County Hospital', 'Sub-County Hospital', 'Sub-County Hospital', 'Sub-County Hospital',
        'Health Centre', 'Private Hospital', 'Prison Health Centre', 'District Hospital', 'Health Centre',
        'Health Centre', 'Health Centre', 'Health Centre', 'Health Centre', 'Dispensary', 'Health Centre',
        'Dispensary', 'Dispensary', 'Sub-County Hospital', 'Health Centre', 'Health Centre', 'Health Centre',
        'University Health Centre', 'Health Centre', 'Health Centre', 'Health Centre', 'Health Centre',
        'Health Centre', 'Health Centre'
    ],
    'capacity': [
        500, 400, 100, 100, 100, 75, 75, 78, 77, 80, 70, 60, 65, 50, 52, 40, 42, 30, 35, 20, 20, 25, 15, 24, 15, 10, 19, 5, 19, 10, 5, 15, 17, 16, 45, 30, 29, 55, 30, 30
    ],
    'ambulance_services': [
        'Available', 'Available', 'Limited', 'Limited', 'Limited', 'Limited', 'Limited', 'Limited',
        'Limited', 'Limited', 'Limited', 'Limited', 'Limited', 'Limited', 'Limited', 'Limited',
        'Limited', 'Limited', 'Limited', 'Limited', 'Limited', 'Limited', 'Limited', 'Limited',
        'Limited', 'Limited', 'Limited', 'Limited', 'Limited', 'Limited', 'Limited', 'Limited',
        'Limited', 'Limited', 'Limited', 'Limited', 'Limited', 'Limited', 'Limited', 'Limited'
    ],
    'contact_number': [
        '+254-57-2055000', '+254-57-2021578', '+254-57-2023456', '+254-57-2034567', '+254-57-2045678',
        '+254-57-2056789', '+254-57-2067890', '+254-57-2078901', '+254-57-2089012', '+254-57-2090123',
        '+254-57-2101234', '+254-57-2112345', '+254-57-2123456', '+254-57-2134567', '+254-57-2145678',
        '+254-57-2156789', '+254-57-2167890', '+254-57-2178901', '+254-57-2189012', '+254-57-2190123',
        '+254-57-2201234', '+254-57-2212345', '+254-57-2223456', '+254-57-2234567', '+254-57-2245678',
        '+254-57-2256789', '+254-57-2267890', '+254-57-2278901', '+254-57-2289012', '+254-57-2290123',
        '+254-57-2301234', '+254-57-2312345', '+254-57-2323456', '+254-57-2334567', '+254-57-2345678',
        '+254-57-2356789', '+254-57-2367890', '+254-57-2378901', '+254-57-2389012', '+254-57-2390123'
    ]
}

hospitals_df = pd.DataFrame(hospitals_data)

ambulances_data = {
    'ambulance_id': [
        'KBA 453D', 'KBC 217F', 'KBD 389G', 'KBE 142H', 'KBF 561J', 'KBG 774K', 'KBH 238L', 'KBJ 965M',
        'KBK 482N', 'KBL 751P', 'KBM 312Q', 'KBN 864R', 'KBP 459S', 'KBQ 287T', 'KBR 913U', 'KBS 506V',
        'KBT 678W', 'KBU 134X', 'KBV 925Y', 'KBX 743Z'
    ],
    'current_location': [
        'Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)',
        'Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)',
        'Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)',
        'Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)',
        'Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)',
        'Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)',
        'Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)',
        'Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)',
        'Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)',
        'Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)',
        'Kisumu County Referral Hospital', 'Kisumu County Referral Hospital', 'Kisumu County Referral Hospital',
        'Kisumu County Referral Hospital', 'Kisumu County Referral Hospital', 'Kisumu County Referral Hospital',
        'Kisumu County Referral Hospital', 'Lumumba Sub-County Hospital', 'Lumumba Sub-County Hospital',
        'Ahero Sub-County Hospital'
    ],
    'latitude': [
        -0.0754, -0.0754, -0.0754, -0.0754, -0.0754, -0.0754, -0.0754, -0.0754, -0.0754, -0.0754,
        -0.0754, -0.0754, -0.0754, -0.0754, -0.0754, -0.0754, -0.0754, -0.1058, -0.1058, -0.1743
    ],
    'longitude': [
        34.7695, 34.7695, 34.7695, 34.7695, 34.7695, 34.7695, 34.7695, 34.7695, 34.7695, 34.7695,
        34.7695, 34.7695, 34.7695, 34.7695, 34.7695, 34.7695, 34.7695, 34.7568, 34.7568, 34.9169
    ],
    'status': [
        'Available', 'Available', 'Available', 'Available', 'Available', 'Available', 'Available', 'Available',
        'Available', 'Available', 'Available', 'Available', 'Available', 'Available', 'Available', 'Available',
        'Available', 'Available', 'Available', 'Available'
    ],
    'driver_name': [
        'John Omondi', 'Mary Achieng', 'Paul Otieno', 'Susan Akinyi', 'David Owino', 'James Okoth',
        'Grace Atieno', 'Peter Onyango', 'Alice Adhiambo', 'Robert Ochieng', 'Sarah Nyongesa',
        'Michael Odhiambo', 'Elizabeth Awuor', 'Daniel Omondi', 'Lucy Anyango', 'Brian Ouma',
        'Patricia Adongo', 'Samuel Owuor', 'Rebecca Aoko', 'Kevin Onyango'
    ],
    'driver_contact': [
        '+254712345678', '+254723456789', '+254734567890', '+254745678901', '+254756789012',
        '+254767890123', '+254778901234', '+254789012345', '+254790123456', '+254701234567',
        '+254712345679', '+254723456780', '+254734567891', '+254745678902', '+254756789013',
        '+254767890124', '+254778901235', '+254789012346', '+254790123457', '+254701234568'
    ],
    'ambulance_type': [
        'Advanced Life Support', 'Basic Life Support', 'Basic Life Support', 'Advanced Life Support',
        'Basic Life Support', 'Basic Life Support', 'Advanced Life Support', 'Basic Life Support',
        'Basic Life Support', 'Advanced Life Support', 'Basic Life Support', 'Basic Life Support',
        'Advanced Life Support', 'Basic Life Support', 'Basic Life Support', 'Advanced Life Support',
        'Basic Life Support', 'Basic Life Support', 'Basic Life Support', 'Advanced Life Support'
    ],
    'equipment': [
        'Defibrillator, Ventilator, Monitor', 'Basic equipment', 'Basic equipment',
        'Defibrillator, Ventilator, Monitor', 'Basic equipment', 'Basic equipment',
        'Defibrillator, Ventilator, Monitor', 'Basic equipment', 'Basic equipment',
        'Defibrillator, Ventilator, Monitor', 'Basic equipment', 'Basic equipment',
        'Defibrillator, Ventilator, Monitor', 'Basic equipment', 'Basic equipment',
        'Defibrillator, Ventilator, Monitor', 'Basic equipment', 'Basic equipment',
        'Basic equipment', 'Defibrillator, Ventilator, Monitor'
    ]
}

# Initialize database with sample ambulances
def initialize_sample_data(db):
    # Check if ambulances already exist
    existing_ambulances = db.session.query(Ambulance).count()
    if existing_ambulances == 0:
        for amb_data in ambulances_data['ambulance_id']:
            idx = ambulances_data['ambulance_id'].index(amb_data)
            ambulance = Ambulance(
                ambulance_id=amb_data,
                current_location=ambulances_data['current_location'][idx],
                latitude=ambulances_data['latitude'][idx],
                longitude=ambulances_data['longitude'][idx],
                status=ambulances_data['status'][idx],
                driver_name=ambulances_data['driver_name'][idx],
                driver_contact=ambulances_data['driver_contact'][idx]
            )
            db.session.add(ambulance)
        db.session.commit()

# =============================================================================
# UI COMPONENTS
# =============================================================================
class DashboardUI:
    def __init__(self, db, analytics):
        self.db = db
        self.analytics = analytics
    
    def display(self):
        st.title("📊 Dashboard Overview")
        
        # KPIs
        kpis = self.analytics.get_kpis()
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.metric("Total Referrals", kpis['total_referrals'])
        with col2:
            st.metric("Active Referrals", kpis['active_referrals'])
        with col3:
            st.metric("Available Ambulances", kpis['available_ambulances'])
        with col4:
            st.metric("Avg Response Time", kpis['avg_response_time'])
        with col5:
            st.metric("Completion Rate", kpis['completion_rate'])
        
        # Charts
        col1, col2 = st.columns(2)
        with col1:
            self.display_referral_trends()
        with col2:
            self.display_ambulance_status()
        
        # Recent referrals
        st.subheader("Recent Referrals")
        self.display_recent_referrals()
    
    def display_referral_trends(self):
        st.subheader("Referral Trends")
        trends = self.analytics.get_referral_trends()
        if not trends.empty:
            fig = px.line(trends, x='date', y='count', title="Daily Referral Trends")
            st.plotly_chart(fig, use_container_width=True, key="referral_trends_chart")
        else:
            st.info("No referral data available")
    
    def display_ambulance_status(self):
        st.subheader("Ambulance Status")
        ambulances = self.db.get_all_ambulances()
        if ambulances:
            status_counts = {}
            for ambulance in ambulances:
                status_counts[ambulance.status] = status_counts.get(ambulance.status, 0) + 1
            fig = px.pie(values=list(status_counts.values()), names=list(status_counts.keys()),
                        title="Ambulance Status Distribution")
            st.plotly_chart(fig, use_container_width=True, key="ambulance_status_chart")
        else:
            st.info("No ambulance data available")
    
    def display_recent_referrals(self):
        patients = self.db.get_all_patients()
        recent_patients = sorted(patients, key=lambda x: x.referral_time, reverse=True)[:5]
        if recent_patients:
            data = []
            for patient in recent_patients:
                data.append({
                    'Patient ID': patient.patient_id,
                    'Name': patient.name,
                    'Condition': patient.condition,
                    'From': patient.referring_hospital,
                    'To': patient.receiving_hospital,
                    'Status': patient.status,
                    'Time': patient.referral_time.strftime('%Y-%m-%d %H:%M')
                })
            st.dataframe(pd.DataFrame(data), use_container_width=True)
        else:
            st.info("No recent referrals")

class ReferralUI:
    def __init__(self, db, notification_service):
        self.db = db
        self.notification_service = notification_service
        self.referral_service = ReferralService(db)
    
    def display(self):
        st.title("📋 Patient Referral Management")
        tab1, tab2, tab3 = st.tabs(["Create Referral", "Active Referrals", "Referral History"])
        with tab1:
            self.create_referral_form()
        with tab2:
            self.display_active_referrals()
        with tab3:
            self.display_referral_history()
    
    def get_receiving_hospitals(self, user_hospital):
        """Get list of receiving hospitals based on user's hospital"""
        if user_hospital == "Kisumu County Referral Hospital":
            # Kisumu County can refer to both JOOTRH and itself
            return [
                "Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)",
                "Kisumu County Referral Hospital"
            ]
        else:
            # All other hospitals can only refer to the two referral hospitals
            return [
                "Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)",
                "Kisumu County Referral Hospital"
            ]
    
    def get_referring_hospitals(self, user_hospital):
        """Get list of referring hospitals based on user's role"""
        if user_hospital in ["All Facilities", "Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)", "Kisumu County Referral Hospital"]:
            # Admin and referral hospitals can see all hospitals
            return hospitals_data['facility_name']
        else:
            # Other hospitals can only see themselves
            return [user_hospital]
    
    def create_referral_form(self):
        st.subheader("Create New Patient Referral")
        user_hospital = st.session_state.user['hospital']
        
        with st.form("referral_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                name = st.text_input("Patient Name*")
                age = st.number_input("Age*", min_value=0, max_value=120, value=30)
                condition = st.text_input("Medical Condition*")
                referring_physician = st.text_input("Referring Physician*")
                
                # Get referring hospitals based on user role
                referring_hospitals = self.get_referring_hospitals(user_hospital)
                referring_hospital = st.selectbox("Referring Hospital*", referring_hospitals)
                
            with col2:
                # Get receiving hospitals based on user role
                receiving_hospitals = self.get_receiving_hospitals(user_hospital)
                receiving_hospital = st.selectbox("Receiving Hospital*", receiving_hospitals)
                
                receiving_physician = st.text_input("Receiving Physician")
                
                # Validate referral rules
                if referring_hospital == receiving_hospital:
                    st.warning("⚠️ Referring and receiving hospitals cannot be the same.")
                
                # Show referral rules
                if user_hospital not in ["All Facilities", "Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)", "Kisumu County Referral Hospital"]:
                    st.info("ℹ️ As a referring hospital, you can only refer patients to Jaramogi Oginga Odinga Teaching & Referral Hospital or Kisumu County Referral Hospital.")
                
            notes = st.text_area("Clinical Notes")
            with st.expander("Additional Medical Information"):
                medical_history = st.text_area("Medical History")
                current_medications = st.text_area("Current Medications")
                allergies = st.text_area("Allergies")
            available_ambulances = self.db.get_available_ambulances()
            ambulance_options = ["Auto-assign"] + [f"{amb.ambulance_id} - {amb.driver_name}" for amb in available_ambulances]
            ambulance_choice = st.selectbox("Ambulance Assignment", ambulance_options)
            
            submitted = st.form_submit_button("Create Referral", use_container_width=True)
            if submitted:
                if not all([name, age, condition, referring_physician, referring_hospital, receiving_hospital]):
                    st.error("Please fill in all required fields (*)")
                elif referring_hospital == receiving_hospital:
                    st.error("Referring and receiving hospitals cannot be the same.")
                else:
                    # Get hospital coordinates
                    referring_hospital_data = hospitals_df[hospitals_df['facility_name'] == referring_hospital].iloc[0]
                    receiving_hospital_data = hospitals_df[hospitals_df['facility_name'] == receiving_hospital].iloc[0]
                    
                    patient_data = {
                        'name': name, 'age': age, 'condition': condition, 'referring_hospital': referring_hospital,
                        'receiving_hospital': receiving_hospital, 'referring_physician': referring_physician,
                        'receiving_physician': receiving_physician, 'notes': notes, 'medical_history': medical_history,
                        'current_medications': current_medications, 'allergies': allergies, 'status': 'Referred',
                        'referring_hospital_lat': referring_hospital_data['latitude'],
                        'referring_hospital_lng': referring_hospital_data['longitude'],
                        'receiving_hospital_lat': receiving_hospital_data['latitude'],
                        'receiving_hospital_lng': receiving_hospital_data['longitude']
                    }
                    if ambulance_choice != "Auto-assign":
                        ambulance_id = ambulance_choice.split(" - ")[0]
                        patient_data['assigned_ambulance'] = ambulance_id
                    patient = self.referral_service.create_referral(patient_data, st.session_state.user)
                    if patient:
                        st.success(f"Referral created successfully! Patient ID: {patient.patient_id}")
                        self.notification_service.send_notification(
                            receiving_hospital, f"New patient referral: {name} - {condition}", 'referral'
                        )
    
    def display_active_referrals(self):
        st.subheader("Active Referrals")
        patients = self.db.get_all_patients()
        user_hospital = st.session_state.user['hospital']
        
        # Filter patients based on user role
        if user_hospital == "All Facilities":
            active_patients = [p for p in patients if p.status not in ['Arrived at Destination', 'Completed']]
        elif user_hospital in ["Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)", "Kisumu County Referral Hospital"]:
            # Show patients referred to this hospital
            active_patients = [p for p in patients if p.receiving_hospital == user_hospital and p.status not in ['Arrived at Destination', 'Completed']]
        else:
            # Show patients referred from this hospital
            active_patients = [p for p in patients if p.referring_hospital == user_hospital and p.status not in ['Arrived at Destination', 'Completed']]
            
        if active_patients:
            data = []
            for patient in active_patients:
                data.append({
                    'Patient ID': patient.patient_id, 'Name': patient.name, 'Condition': patient.condition,
                    'From': patient.referring_hospital, 'To': patient.receiving_hospital,
                    'Status': patient.status, 'Ambulance': patient.assigned_ambulance or 'Not assigned'
                })
            df = pd.DataFrame(data)
            st.dataframe(df, use_container_width=True)
            
            # Patient actions
            st.subheader("Patient Actions")
            for patient in active_patients:
                with st.expander(f"Actions for {patient.name} ({patient.patient_id})"):
                    self.display_patient_actions(patient)
        else:
            st.info("No active referrals")
    
    def display_patient_actions(self, patient):
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button(f"Assign Ambulance", key=f"assign_{patient.patient_id}", use_container_width=True):
                st.session_state[f'assign_ambulance_{patient.patient_id}'] = True
            
            if st.session_state.get(f'assign_ambulance_{patient.patient_id}'):
                available_ambulances = self.db.get_available_ambulances()
                if available_ambulances:
                    ambulance_options = [f"{amb.ambulance_id} - {amb.driver_name}" for amb in available_ambulances]
                    selected_ambulance = st.selectbox("Select Ambulance", ambulance_options, key=f"amb_select_{patient.patient_id}")
                    if st.button("Confirm Assignment", key=f"confirm_{patient.patient_id}", use_container_width=True):
                        ambulance_id = selected_ambulance.split(" - ")[0]
                        if self.referral_service.assign_ambulance(patient.patient_id, ambulance_id):
                            st.success("Ambulance assigned successfully!")
                            st.session_state[f'assign_ambulance_{patient.patient_id}'] = False
                            st.rerun()
                else:
                    st.warning("No available ambulances")
        
        with col2:
            if st.button("Update Status", key=f"status_{patient.patient_id}", use_container_width=True):
                st.session_state[f'update_status_{patient.patient_id}'] = True
            
            if st.session_state.get(f'update_status_{patient.patient_id}'):
                new_status = st.selectbox("New Status", 
                    ["Referred", "Ambulance Dispatched", "Patient Picked Up", 
                     "Transporting to Destination", "Arrived at Destination"],
                    key=f"status_select_{patient.patient_id}")
                if st.button("Update", key=f"update_{patient.patient_id}", use_container_width=True):
                    patient.status = new_status
                    self.db.session.commit()
                    st.success("Status updated!")
                    st.session_state[f'update_status_{patient.patient_id}'] = False
                    st.rerun()
        
        with col3:
            if st.button("View Details", key=f"details_{patient.patient_id}", use_container_width=True):
                st.session_state[f'view_details_{patient.patient_id}'] = True
            
            if st.session_state.get(f'view_details_{patient.patient_id}'):
                st.write(f"**Medical History:** {patient.medical_history}")
                st.write(f"**Medications:** {patient.current_medications}")
                st.write(f"**Allergies:** {patient.allergies}")
                if st.button("Close", key=f"close_{patient.patient_id}", use_container_width=True):
                    st.session_state[f'view_details_{patient.patient_id}'] = False
                    st.rerun()
    
    def display_referral_history(self):
        st.subheader("Referral History")
        patients = self.db.get_all_patients()
        user_hospital = st.session_state.user['hospital']
        
        # Filter patients based on user role
        if user_hospital == "All Facilities":
            filtered_patients = patients
        elif user_hospital in ["Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)", "Kisumu County Referral Hospital"]:
            # Show patients referred to this hospital
            filtered_patients = [p for p in patients if p.receiving_hospital == user_hospital]
        else:
            # Show patients referred from this hospital
            filtered_patients = [p for p in patients if p.referring_hospital == user_hospital]
            
        if filtered_patients:
            data = []
            for patient in filtered_patients:
                data.append({
                    'Patient ID': patient.patient_id, 'Name': patient.name, 'Condition': patient.condition,
                    'From': patient.referring_hospital, 'To': patient.receiving_hospital,
                    'Status': patient.status, 'Referral Time': patient.referral_time.strftime('%Y-%m-%d %H:%M'),
                    'Ambulance': patient.assigned_ambulance or 'Not assigned'
                })
            df = pd.DataFrame(data)
            st.dataframe(df, use_container_width=True)
        else:
            st.info("No referral history")

class TrackingUI:
    def __init__(self, db):
        self.db = db
        self.map_utils = MapUtils()
    
    def display(self):
        st.title("🚑 Live Ambulance Tracking")
        
        # Auto-refresh every 10 seconds
        col1, col2 = st.columns([3, 1])
        with col2:
            if st.button("🔄 Refresh Map", use_container_width=True):
                st.rerun()
        
        st.markdown("### 🗺️ Real-time Ambulance Tracking")
        
        # Get active transfers
        patients = self.db.get_all_patients()
        active_transfers = [p for p in patients if p.status in ['Ambulance Dispatched', 'Patient Picked Up', 'Transporting to Destination']]
        
        if active_transfers:
            for patient in active_transfers:
                with st.expander(f"🚑 {patient.name} - {patient.condition}", expanded=True):
                    col1, col2 = st.columns([2, 1])
                    
                    with col1:
                        # Get ambulance data
                        ambulance = None
                        if patient.assigned_ambulance:
                            ambulance = self.db.session.query(Ambulance).filter(
                                Ambulance.ambulance_id == patient.assigned_ambulance
                            ).first()
                        
                        if ambulance and patient.referring_hospital_lat and patient.receiving_hospital_lat:
                            # Create Uber-style map
                            map_obj = self.map_utils.create_uber_style_map(patient, ambulance, hospitals_df)
                            if map_obj:
                                st.pydeck_chart(map_obj)
                            
                            # Display real-time information
                            st.subheader("📍 Real-time Information")
                            col_info1, col_info2, col_info3 = st.columns(3)
                            
                            with col_info1:
                                st.metric("Ambulance", ambulance.ambulance_id)
                                st.metric("Driver", ambulance.driver_name)
                            
                            with col_info2:
                                st.metric("Current Location", ambulance.current_location or "Unknown")
                                if ambulance.last_location_update:
                                    time_diff = datetime.utcnow() - ambulance.last_location_update
                                    st.metric("Last Update", f"{time_diff.seconds // 60} min ago")
                            
                            with col_info3:
                                st.metric("Status", patient.status)
                                st.metric("Destination", patient.receiving_hospital)
                        else:
                            st.info("Waiting for ambulance assignment or location data...")
                    
                    with col2:
                        st.subheader("📋 Patient Details")
                        st.write(f"**Patient:** {patient.name}")
                        st.write(f"**Age:** {patient.age}")
                        st.write(f"**Condition:** {patient.condition}")
                        st.write(f"**From:** {patient.referring_hospital}")
                        st.write(f"**To:** {patient.receiving_hospital}")
                        
                        # Progress bar
                        status_progress = {
                            'Referred': 0, 
                            'Ambulance Dispatched': 25, 
                            'Patient Picked Up': 50,
                            'Transporting to Destination': 75, 
                            'Arrived at Destination': 100
                        }
                        progress = status_progress.get(patient.status, 0)
                        st.progress(progress / 100)
                        st.write(f"**Journey Progress:** {progress}%")
                        
                        # ETA estimation (simplified)
                        if ambulance and ambulance.last_location_update:
                            eta_minutes = 15  # Simplified ETA calculation
                            st.metric("Estimated Arrival", f"{eta_minutes} minutes")
        else:
            st.info("No active patient transfers to track")
            
        # Display all ambulances
        st.markdown("### 🚑 All Ambulances")
        self.display_ambulance_list()
    
    def display_ambulance_list(self):
        ambulances = self.db.get_all_ambulances()
        for ambulance in ambulances:
            status_color = "🟢" if ambulance.status == 'Available' else "🔴"
            with st.expander(f"{status_color} {ambulance.ambulance_id} - {ambulance.driver_name}"):
                st.write(f"**Status:** {ambulance.status}")
                st.write(f"**Location:** {ambulance.current_location}")
                st.write(f"**Contact:** {ambulance.driver_contact}")
                if ambulance.current_patient:
                    patient = self.db.get_patient_by_id(ambulance.current_patient)
                    if patient:
                        st.write(f"**Current Patient:** {patient.name}")
                        st.write(f"**Destination:** {patient.receiving_hospital}")

class HandoverUI:
    def __init__(self, db):
        self.db = db
    
    def display(self):
        st.title("📄 Patient Handover Management")
        tab1, tab2 = st.tabs(["Create Handover Form", "Handover History"])
        with tab1:
            self.create_handover_form()
        with tab2:
            self.display_handover_history()
    
    def create_handover_form(self):
        st.subheader("Create Handover Form")
        patients = self.db.get_all_patients()
        user_hospital = st.session_state.user['hospital']
        
        # Filter eligible patients based on user role
        if user_hospital == "All Facilities":
            eligible_patients = [p for p in patients if p.status == 'Arrived at Destination']
        else:
            eligible_patients = [p for p in patients if p.receiving_hospital == user_hospital and p.status == 'Arrived at Destination']
            
        if not eligible_patients:
            st.info("No patients eligible for handover (must have status 'Arrived at Destination')")
            return
        
        patient_options = {f"{p.patient_id} - {p.name}": p for p in eligible_patients}
        selected_patient_key = st.selectbox("Select Patient", list(patient_options.keys()))
        selected_patient = patient_options[selected_patient_key]
        
        with st.form("handover_form", clear_on_submit=True):
            st.write(f"**Patient:** {selected_patient.name}")
            st.write(f"**Condition:** {selected_patient.condition}")
            st.write(f"**From:** {selected_patient.referring_hospital}")
            st.write(f"**To:** {selected_patient.receiving_hospital}")
            
            st.subheader("Vital Signs at Handover")
            col1, col2 = st.columns(2)
            with col1:
                blood_pressure = st.text_input("Blood Pressure", value="120/80")
                heart_rate = st.number_input("Heart Rate (bpm)", min_value=0, max_value=200, value=72)
            with col2:
                temperature = st.number_input("Temperature (°C)", min_value=30.0, max_value=45.0, value=36.6)
                oxygen_saturation = st.number_input("Oxygen Saturation (%)", min_value=0, max_value=100, value=98)
            
            st.subheader("Handover Details")
            receiving_physician = st.text_input("Receiving Physician*")
            handover_notes = st.text_area("Handover Notes")
            
            with st.expander("Additional Information"):
                condition_changes = st.text_area("Condition Changes During Transfer")
                interventions = st.text_area("Interventions During Transfer")
                medications_administered = st.text_area("Medications Administered")
            
            submitted = st.form_submit_button("Complete Handover", use_container_width=True)
            if submitted:
                if not receiving_physician:
                    st.error("Please enter the receiving physician")
                else:
                    handover_data = {
                        'patient_id': selected_patient.patient_id, 'patient_name': selected_patient.name,
                        'age': selected_patient.age, 'condition': selected_patient.condition,
                        'referring_hospital': selected_patient.referring_hospital,
                        'receiving_hospital': selected_patient.receiving_hospital,
                        'referring_physician': selected_patient.referring_physician,
                        'receiving_physician': receiving_physician, 'vital_signs': {
                            'blood_pressure': blood_pressure, 'heart_rate': heart_rate,
                            'temperature': temperature, 'oxygen_saturation': oxygen_saturation
                        }, 'medical_history': selected_patient.medical_history,
                        'current_medications': selected_patient.current_medications,
                        'allergies': selected_patient.allergies, 'notes': handover_notes,
                        'ambulance_id': selected_patient.assigned_ambulance,
                        'created_by': st.session_state.user['role']
                    }
                    handover = self.db.add_handover_form(handover_data)
                    selected_patient.status = 'Completed'
                    selected_patient.receiving_physician = receiving_physician
                    self.db.session.commit()
                    st.success("Handover completed successfully!")
                    st.balloons()
    
    def display_handover_history(self):
        st.subheader("Handover History")
        handovers = self.db.session.query(HandoverForm).all()
        user_hospital = st.session_state.user['hospital']
        
        # Filter handovers based on user role
        if user_hospital != "All Facilities":
            handovers = [h for h in handovers if h.receiving_hospital == user_hospital]
            
        if handovers:
            for handover in handovers:
                with st.expander(f"{handover.patient_name} - {handover.transfer_time.strftime('%Y-%m-%d %H:%M')}"):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.write(f"**Patient ID:** {handover.patient_id}")
                        st.write(f"**Age:** {handover.age}")
                        st.write(f"**Condition:** {handover.condition}")
                        st.write(f"**Referring Hospital:** {handover.referring_hospital}")
                        st.write(f"**Receiving Hospital:** {handover.receiving_hospital}")
                    with col2:
                        st.write(f"**Referring Physician:** {handover.referring_physician}")
                        st.write(f"**Receiving Physician:** {handover.receiving_physician}")
                        st.write(f"**Ambulance:** {handover.ambulance_id}")
                        st.write(f"**Handover Time:** {handover.transfer_time.strftime('%Y-%m-%d %H:%M')}")
                    
                    if handover.vital_signs:
                        st.subheader("Vital Signs at Handover")
                        vitals = handover.vital_signs
                        col1, col2, col3, col4 = st.columns(4)
                        with col1:
                            st.metric("BP", vitals.get('blood_pressure', 'N/A'))
                        with col2:
                            st.metric("HR", f"{vitals.get('heart_rate', 'N/A')} bpm")
                        with col3:
                            st.metric("Temp", f"{vitals.get('temperature', 'N/A')}°C")
                        with col4:
                            st.metric("SpO2", f"{vitals.get('oxygen_saturation', 'N/A')}%")
                    
                    if handover.notes:
                        st.write(f"**Handover Notes:** {handover.notes}")
        else:
            st.info("No handover forms completed")

class CommunicationUI:
    def __init__(self, db, notification_service):
        self.db = db
        self.notification_service = notification_service
    
    def display(self):
        st.title("💬 Communication Center")
        tab1, tab2, tab3 = st.tabs(["Send Notifications", "Message Templates", "Communication Log"])
        with tab1:
            self.send_notifications()
        with tab2:
            self.message_templates()
        with tab3:
            self.communication_log()
    
    def send_notifications(self):
        st.subheader("Send Notifications")
        with st.form("notification_form"):
            notification_type = st.selectbox(
                "Notification Type",
                ["Referral Alert", "Ambulance Dispatch", "Patient Arrival", "Emergency", "General Update"]
            )
            recipient_type = st.radio("Recipient", ["Hospital", "Ambulance Driver", "Specific Contact"])
            if recipient_type == "Hospital":
                recipient = st.selectbox("Select Hospital", 
                    ["Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)",
                     "Kisumu County Referral Hospital", "Lumumba Sub-County Hospital", "All Hospitals"])
            elif recipient_type == "Ambulance Driver":
                ambulances = self.db.get_all_ambulances()
                recipient = st.selectbox("Select Driver", 
                    [f"{amb.ambulance_id} - {amb.driver_name}" for amb in ambulances])
            else:
                recipient = st.text_input("Contact Number/Email")
            subject = st.text_input("Subject", value=f"{notification_type} Notification")
            message = st.text_area("Message", height=150)
            col1, col2, col3 = st.columns(3)
            with col1:
                send_sms = st.checkbox("Send SMS", value=True)
            with col2:
                send_email = st.checkbox("Send Email")
            with col3:
                urgent = st.checkbox("Urgent", value=False)
            
            submitted = st.form_submit_button("Send Notification", use_container_width=True)
            if submitted:
                if not message:
                    st.error("Please enter a message")
                else:
                    if send_sms:
                        st.success("📱 SMS notification prepared for sending")
                    if send_email:
                        st.success("📧 Email notification prepared for sending")
                    if urgent:
                        st.warning("🚨 URGENT notification marked")
                    st.info(f"Notification will be sent to: {recipient}")
    
    def message_templates(self):
        st.subheader("Message Templates")
        templates = {
            "New Referral": "New patient referral received: {patient_name} with {condition}. Please prepare for arrival.",
            "Ambulance Dispatch": "Ambulance {ambulance_id} dispatched for patient {patient_name}. ETA: {eta} minutes.",
            "Patient Arrival": "Patient {patient_name} has arrived at {hospital}. Condition: {condition}.",
            "Emergency": "EMERGENCY: {message}. Immediate response required.",
            "Status Update": "Patient {patient_name} status update: {status}. Current location: {location}."
        }
        selected_template = st.selectbox("Select Template", list(templates.keys()))
        st.text_area("Template Content", templates[selected_template], height=100)
        
        st.subheader("Customize Template")
        custom_message = st.text_area("Custom Message", templates[selected_template], height=100)
        if st.button("Save as New Template", use_container_width=True):
            st.success("Template saved successfully!")
    
    def communication_log(self):
        st.subheader("Communication Log")
        communications = [
            {
                "timestamp": "2024-01-15 10:30:00",
                "type": "SMS",
                "recipient": "JOOTRH",
                "message": "New referral: John Doe - Cardiac Emergency",
                "status": "Delivered"
            },
            {
                "timestamp": "2024-01-15 10:25:00",
                "type": "Email",
                "recipient": "admin@kisumu.gov",
                "message": "Weekly report generated",
                "status": "Sent"
            },
            {
                "timestamp": "2024-01-15 09:45:00",
                "type": "SMS",
                "recipient": "Driver - John Omondi",
                "message": "New assignment: Patient ID PAT1234",
                "status": "Delivered"
            }
        ]
        for comm in communications:
            with st.expander(f"{comm['timestamp']} - {comm['type']} to {comm['recipient']}"):
                st.write(f"**Message:** {comm['message']}")
                st.write(f"**Status:** {comm['status']}")
                if st.button("Resend", key=f"resend_{comm['timestamp']}", use_container_width=True):
                    st.success("Message resent successfully!")

class ReportsUI:
    def __init__(self, db, analytics):
        self.db = db
        self.analytics = analytics
        self.pdf_exporter = PDFExporter()
    
    def display(self):
        st.title("📈 Reports & Analytics")
        tab1, tab2, tab3, tab4 = st.tabs(["Performance Metrics", "Hospital Analytics", "Ambulance Reports", "Export Data"])
        with tab1:
            self.performance_metrics()
        with tab2:
            self.hospital_analytics()
        with tab3:
            self.ambulance_reports()
        with tab4:
            self.export_data()
    
    def performance_metrics(self):
        st.subheader("Performance Metrics")
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("Start Date", datetime.now() - timedelta(days=30))
        with col2:
            end_date = st.date_input("End Date", datetime.now())
        
        kpis = self.analytics.get_kpis()
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Referrals", kpis['total_referrals'])
        with col2:
            st.metric("Completion Rate", kpis['completion_rate'])
        with col3:
            st.metric("Avg Response Time", kpis['avg_response_time'])
        with col4:
            st.metric("Active Transfers", kpis['active_referrals'])
        
        st.subheader("Response Time Trends")
        dates = pd.date_range(start=start_date, end=end_date, freq='D')
        response_times = [15 + i % 5 for i in range(len(dates))]
        response_df = pd.DataFrame({'Date': dates, 'Response Time (min)': response_times})
        fig = px.line(response_df, x='Date', y='Response Time (min)', title="Average Response Time Trend")
        st.plotly_chart(fig, use_container_width=True, key="response_time_chart")
        
        st.subheader("Referral Reasons")
        patients = self.db.get_all_patients()
        if patients:
            conditions = [p.condition for p in patients]
            condition_counts = pd.Series(conditions).value_counts()
            fig = px.pie(values=condition_counts.values, names=condition_counts.index,
                        title="Referral Reasons Distribution")
            st.plotly_chart(fig, use_container_width=True, key="referral_reasons_chart")
    
    def hospital_analytics(self):
        st.subheader("Hospital Performance")
        hospitals_stats = self.analytics.get_hospital_stats()
        if not hospitals_stats.empty:
            hospital_referrals = hospitals_stats.groupby('hospital')['count'].sum().reset_index()
            fig = px.bar(hospital_referrals, x='hospital', y='count', title="Total Referrals by Hospital")
            st.plotly_chart(fig, use_container_width=True, key="hospital_referrals_chart")
            
            fig = px.sunburst(hospitals_stats, path=['hospital', 'status'], values='count',
                             title="Referral Status by Hospital")
            st.plotly_chart(fig, use_container_width=True, key="hospital_status_chart")
        else:
            st.info("No hospital data available")
    
    def ambulance_reports(self):
        st.subheader("Ambulance Utilization")
        ambulances = self.db.get_all_ambulances()
        if ambulances:
            status_counts = {}
            for ambulance in ambulances:
                status_counts[ambulance.status] = status_counts.get(ambulance.status, 0) + 1
            
            # FIXED: Added unique key to prevent duplicate element ID error
            fig = px.pie(values=list(status_counts.values()), names=list(status_counts.keys()),
                        title="Ambulance Status Distribution")
            st.plotly_chart(fig, use_container_width=True, key="ambulance_status_pie_chart")
            
            st.subheader("Ambulance Utilization Details")
            ambulance_data = []
            for ambulance in ambulances:
                utilization = "High" if ambulance.status != 'Available' else "Low"
                ambulance_data.append({
                    'Ambulance ID': ambulance.ambulance_id, 'Driver': ambulance.driver_name,
                    'Status': ambulance.status, 'Utilization': utilization,
                    'Current Patient': ambulance.current_patient or 'None', 'Location': ambulance.current_location
                })
            st.dataframe(pd.DataFrame(ambulance_data), use_container_width=True)
        else:
            st.info("No ambulance data available")
    
    def export_data(self):
        st.subheader("Data Export")
        col1, col2 = st.columns(2)
        with col1:
            st.download_button(
                label="📊 Export Referrals as CSV",
                data=self.export_referrals_csv(),
                file_name=f"referrals_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                use_container_width=True
            )
            st.download_button(
                label="🚑 Export Ambulance Data as CSV",
                data=self.export_ambulances_csv(),
                file_name=f"ambulances_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                use_container_width=True
            )
        with col2:
            if st.button("📄 Generate PDF Report", use_container_width=True):
                st.info("PDF report generation feature would be implemented here")
            if st.button("📈 Export Analytics", use_container_width=True):
                st.info("Analytics export feature would be implemented here")
    
    def export_referrals_csv(self):
        patients = self.db.get_all_patients()
        data = []
        for patient in patients:
            data.append({
                'Patient ID': patient.patient_id, 'Name': patient.name, 'Age': patient.age,
                'Condition': patient.condition, 'Referring Hospital': patient.referring_hospital,
                'Receiving Hospital': patient.receiving_hospital, 'Status': patient.status,
                'Referral Time': patient.referral_time, 'Assigned Ambulance': patient.assigned_ambulance
            })
        df = pd.DataFrame(data)
        return df.to_csv(index=False)
    
    def export_ambulances_csv(self):
        ambulances = self.db.get_all_ambulances()
        data = []
        for ambulance in ambulances:
            data.append({
                'Ambulance ID': ambulance.ambulance_id, 'Driver': ambulance.driver_name,
                'Contact': ambulance.driver_contact, 'Status': ambulance.status,
                'Location': ambulance.current_location, 'Current Patient': ambulance.current_patient
            })
        df = pd.DataFrame(data)
        return df.to_csv(index=False)

class DriverUI:
    def __init__(self, db, notification_service):
        self.db = db
        self.notification_service = notification_service
        self.location_simulator = LocationSimulator(db)
    
    def display_driver_dashboard(self):
        st.header("🚑 Ambulance Driver Dashboard")
        driver_name = st.session_state.user.get('name', st.session_state.user['role'])
        ambulance = self.db.session.query(Ambulance).filter(Ambulance.driver_name == driver_name).first()
        
        if not ambulance:
            st.error("No ambulance assigned to you")
            return
        
        # Display driver information
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Ambulance ID", ambulance.ambulance_id)
        with col2:
            st.metric("Status", ambulance.status)
        with col3:
            st.metric("Location", ambulance.current_location)
        
        # Display current mission if any
        if ambulance.current_patient and ambulance.status == 'On Transfer':
            patient = self.db.get_patient_by_id(ambulance.current_patient)
            if patient:
                st.subheader("Current Mission")
                col1, col2 = st.columns(2)
                with col1:
                    st.write(f"**Patient:** {patient.name}")
                    st.write(f"**Condition:** {patient.condition}")
                    st.write(f"**From:** {patient.referring_hospital}")
                    st.write(f"**To:** {patient.receiving_hospital}")
                    st.write(f"**Status:** {patient.status}")
                
                with col2:
                    # Real-time location sharing
                    st.subheader("📍 Real-time Location Sharing")
                    
                    # Show current location on map
                    if ambulance.latitude and ambulance.longitude:
                        # Create a simple map showing ambulance and hospitals
                        map_data = pd.DataFrame({
                            'lat': [ambulance.latitude, patient.referring_hospital_lat, patient.receiving_hospital_lat],
                            'lon': [ambulance.longitude, patient.referring_hospital_lng, patient.receiving_hospital_lng],
                            'name': ['Ambulance', 'Referring Hospital', 'Receiving Hospital']
                        })
                        st.map(map_data, use_container_width=True)
                    
                    # Location update controls
                    st.subheader("📍 Update Location")
                    with st.form("location_update_form"):
                        new_lat = st.number_input("Latitude", value=ambulance.latitude or -0.0916)
                        new_lng = st.number_input("Longitude", value=ambulance.longitude or 34.7680)
                        location_name = st.text_input("Location Name", value=ambulance.current_location or "En route")
                        
                        if st.form_submit_button("Update Location", use_container_width=True):
                            ambulance_service = AmbulanceService(self.db)
                            if ambulance_service.update_ambulance_location(
                                ambulance.ambulance_id, new_lat, new_lng, location_name, patient.patient_id
                            ):
                                st.success("Location updated! Hospitals can now see your current position.")
                
                # Real-time Communication Section
                st.subheader("💬 Real-time Communication")
                self.display_communication_panel(patient, ambulance)
                
                # Quick actions
                st.subheader("Quick Actions")
                col1, col2, col3 = st.columns(3)
                with col1:
                    if st.button("📝 Update Vitals", use_container_width=True):
                        self.show_vitals_form(patient)
                with col2:
                    if st.button("📍 Update Location", use_container_width=True):
                        self.update_location_form(ambulance)
                with col3:
                    if st.button("🆘 Emergency", use_container_width=True, type="secondary"):
                        self.send_emergency_alert(ambulance, patient)
                
                # Mission completion
                st.subheader("Mission Completion")
                if st.button("✅ Mark Patient Delivered", use_container_width=True, type="primary"):
                    self.complete_mission(ambulance, patient)
        
        elif ambulance.status == 'Available':
            st.info("Awaiting assignment...")
            # Show available missions
            available_patients = self.db.session.query(Patient).filter(
                Patient.status == 'Referred',
                Patient.assigned_ambulance.is_(None)
            ).all()
            
            if available_patients:
                st.subheader("Available Missions")
                for patient in available_patients:
                    with st.expander(f"Mission: {patient.name} - {patient.condition}"):
                        st.write(f"**From:** {patient.referring_hospital}")
                        st.write(f"**To:** {patient.receiving_hospital}")
                        if st.button("Accept Mission", key=f"accept_{patient.patient_id}", use_container_width=True):
                            ambulance.current_patient = patient.patient_id
                            ambulance.status = 'On Transfer'
                            patient.assigned_ambulance = ambulance.ambulance_id
                            patient.status = 'Ambulance Dispatched'
                            self.db.session.commit()
                            
                            # Start location simulation
                            if patient.referring_hospital_lat and patient.receiving_hospital_lat:
                                # In a real app, this would use actual GPS
                                # For demo, we simulate movement
                                thread = threading.Thread(
                                    target=self.location_simulator.start_simulation,
                                    args=(
                                        ambulance.ambulance_id,
                                        patient.patient_id,
                                        ambulance.latitude,
                                        ambulance.longitude,
                                        patient.receiving_hospital_lat,
                                        patient.receiving_hospital_lng
                                    )
                                )
                                thread.daemon = True
                                thread.start()
                            
                            st.success(f"Mission accepted! Assigned to patient {patient.name}")
                            st.rerun()
        
        # Quick status updates
        st.subheader("Quick Status Updates")
        self.quick_actions(ambulance)
    
    def display_communication_panel(self, patient, ambulance):
        """Display real-time communication panel for drivers"""
        col1, col2 = st.columns([2, 1])
        
        with col1:
            st.subheader("Chat with Hospitals")
            
            # Display existing messages
            communications = self.db.get_communications_for_patient(patient.patient_id)
            if communications:
                st.write("**Recent Messages:**")
                for comm in communications[:5]:  # Show last 5 messages
                    timestamp = comm.timestamp.strftime('%H:%M')
                    if comm.sender == 'Driver':
                        st.markdown(f"**You** ({timestamp}): {comm.message}")
                    else:
                        st.markdown(f"**{comm.sender}** ({timestamp}): {comm.message}")
            else:
                st.info("No messages yet")
            
            # Send new message
            with st.form("message_form"):
                message = st.text_area("Type your message", placeholder="Update on patient condition, ETA, or any issues...")
                recipient = st.selectbox("Send to", 
                    [patient.referring_hospital, patient.receiving_hospital, "Both Hospitals"])
                if st.form_submit_button("Send Message", use_container_width=True):
                    if message:
                        # Save message to database
                        if recipient == "Both Hospitals":
                            hospitals = [patient.referring_hospital, patient.receiving_hospital]
                        else:
                            hospitals = [recipient]
                        
                        for hospital in hospitals:
                            comm_data = {
                                'patient_id': patient.patient_id,
                                'ambulance_id': ambulance.ambulance_id,
                                'sender': 'Driver',
                                'receiver': hospital,
                                'message': message,
                                'message_type': 'driver_hospital'
                            }
                            self.db.add_communication(comm_data)
                        
                        st.success("Message sent!")
                        st.rerun()
                    else:
                        st.error("Please enter a message")
        
        with col2:
            st.subheader("Quick Updates")
            
            # Pre-defined quick messages
            quick_messages = {
                "ETA 10 mins": "Estimated arrival in 10 minutes",
                "Patient stable": "Patient condition is stable during transport",
                "Traffic delay": "Experiencing traffic delays, will update ETA",
                "Need assistance": "Require medical assistance upon arrival",
                "Vitals normal": "Patient vital signs are within normal range"
            }
            
            for label, message in quick_messages.items():
                if st.button(label, key=f"quick_{label}", use_container_width=True):
                    # Send to both hospitals
                    for hospital in [patient.referring_hospital, patient.receiving_hospital]:
                        comm_data = {
                            'patient_id': patient.patient_id,
                            'ambulance_id': ambulance.ambulance_id,
                            'sender': 'Driver',
                            'receiver': hospital,
                            'message': f"Quick update: {message}",
                            'message_type': 'driver_hospital'
                        }
                        self.db.add_communication(comm_data)
                    st.success("Quick update sent!")
    
    def show_vitals_form(self, patient):
        with st.form("vitals_form"):
            st.subheader("Update Patient Vitals")
            bp = st.text_input("Blood Pressure", value="120/80")
            heart_rate = st.number_input("Heart Rate (bpm)", min_value=0, max_value=200, value=72)
            spo2 = st.number_input("Oxygen Saturation (%)", min_value=0, max_value=100, value=98)
            respiratory_rate = st.number_input("Respiratory Rate", min_value=0, max_value=60, value=16)
            notes = st.text_area("Observations")
            if st.form_submit_button("Update Vitals", use_container_width=True):
                patient.vital_signs = {
                    'blood_pressure': bp, 
                    'heart_rate': heart_rate, 
                    'oxygen_saturation': spo2,
                    'respiratory_rate': respiratory_rate,
                    'notes': notes, 
                    'timestamp': datetime.utcnow().isoformat()
                }
                self.db.session.commit()
                
                # Notify hospitals
                for hospital in [patient.referring_hospital, patient.receiving_hospital]:
                    comm_data = {
                        'patient_id': patient.patient_id,
                        'sender': 'Driver',
                        'receiver': hospital,
                        'message': f"Vitals updated: BP {bp}, HR {heart_rate}bpm, SpO2 {spo2}%",
                        'message_type': 'vitals_update'
                    }
                    self.db.add_communication(comm_data)
                
                st.success("Vitals updated and notified hospitals!")
    
    def update_location_form(self, ambulance):
        with st.form("location_form"):
            st.subheader("Update Current Location")
            location_name = st.text_input("Location Name", value=ambulance.current_location)
            latitude = st.number_input("Latitude", value=ambulance.latitude or -0.0916)
            longitude = st.number_input("Longitude", value=ambulance.longitude or 34.7680)
            if st.form_submit_button("Update Location", use_container_width=True):
                ambulance_service = AmbulanceService(self.db)
                if ambulance_service.update_ambulance_location(
                    ambulance.ambulance_id, latitude, longitude, location_name, ambulance.current_patient
                ):
                    st.success("Location updated! Hospitals can now see your current position.")
    
    def send_emergency_alert(self, ambulance, patient):
        st.error("🚨 EMERGENCY ALERT SENT!")
        emergency_message = f"EMERGENCY: Ambulance {ambulance.ambulance_id} requires immediate assistance!"
        
        # Notify both hospitals and control center
        recipients = [patient.referring_hospital, patient.receiving_hospital, "Control Center"]
        for recipient in recipients:
            comm_data = {
                'patient_id': patient.patient_id,
                'ambulance_id': ambulance.ambulance_id,
                'sender': 'Driver',
                'receiver': recipient,
                'message': emergency_message,
                'message_type': 'emergency'
            }
            self.db.add_communication(comm_data)
        
        self.notification_service.send_notification(
            "Control Center",
            emergency_message,
            'emergency'
        )
    
    def complete_mission(self, ambulance, patient):
        ambulance.status = 'Available'
        ambulance.current_patient = None
        ambulance.mission_complete = True
        patient.status = 'Arrived at Destination'
        self.db.session.commit()
        
        # Notify hospitals
        arrival_message = f"Patient {patient.name} has arrived via ambulance {ambulance.ambulance_id}"
        for hospital in [patient.referring_hospital, patient.receiving_hospital]:
            comm_data = {
                'patient_id': patient.patient_id,
                'ambulance_id': ambulance.ambulance_id,
                'sender': 'Driver',
                'receiver': hospital,
                'message': arrival_message,
                'message_type': 'arrival_notification'
            }
            self.db.add_communication(comm_data)
        
        self.notification_service.send_notification(
            patient.receiving_hospital,
            arrival_message,
            'arrival'
        )
        st.success("Mission completed! Patient delivered successfully.")
        st.balloons()
    
    def quick_actions(self, ambulance):
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("🔄 Mark Available", use_container_width=True):
                ambulance.status = 'Available'
                ambulance.current_patient = None
                self.db.session.commit()
                st.success("Status updated to Available")
                st.rerun()
        with col2:
            if st.button("⛑️ Mark On Break", use_container_width=True):
                ambulance.status = 'On Break'
                self.db.session.commit()
                st.success("Status updated to On Break")
                st.rerun()
        with col3:
            if st.button("🔧 Maintenance", use_container_width=True):
                ambulance.status = 'Maintenance'
                self.db.session.commit()
                st.success("Status updated to Maintenance")
                st.rerun()

# =============================================================================
# MAIN APPLICATION
# =============================================================================
class HospitalReferralApp:
    def __init__(self):
        self.auth = Authentication()
        self.db = Database()
        # Initialize sample data
        initialize_sample_data(self.db)
        self.analytics = AnalyticsService(self.db)
        self.notifications = NotificationService()
        self.dashboard_ui = DashboardUI(self.db, self.analytics)
        self.referral_ui = ReferralUI(self.db, self.notifications)
        self.tracking_ui = TrackingUI(self.db)
        self.handover_ui = HandoverUI(self.db)
        self.communication_ui = CommunicationUI(self.db, self.notifications)
        self.reports_ui = ReportsUI(self.db, self.analytics)
        self.driver_ui = DriverUI(self.db, self.notifications)
        
        if 'authenticated' not in st.session_state:
            st.session_state.authenticated = False
        if 'user' not in st.session_state:
            st.session_state.user = None
        if 'simulation_running' not in st.session_state:
            st.session_state.simulation_running = False
    
    def run(self):
        self.auth.setup_auth_ui()
        if st.session_state.get('authenticated'):
            self.render_main_app()
        else:
            self.render_login_page()
    
    def render_login_page(self):
        st.title("🏥 Kisumu County Hospital Referral System")
        st.markdown("""
        ## Welcome to the Hospital Referral & Ambulance Tracking System
        
        Please login using the sidebar to access the system.
        
        **Demo Credentials:**
        - Admin: `admin` / `admin123`
        - Hospital Staff (JOOTRH): `hospital_staff` / `staff123`
        - Hospital Staff (Kisumu County): `kisumu_staff` / `kisumu123`
        - Ambulance Driver: `driver` / `driver123`
        """)
        
        st.subheader("System Overview")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Hospitals in Network", "40")
        with col2:
            st.metric("Ambulances", "20")
        with col3:
            st.metric("Coverage Area", "Kisumu County")
        
        # Display referral rules
        st.subheader("Referral Rules")
        st.markdown("""
        - **Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)**: Can receive referrals only
        - **Kisumu County Referral Hospital**: Can both refer and receive patients
        - **Other 38 Hospitals**: Can only refer patients to the two referral hospitals
        """)
    
    def render_main_app(self):
        user_role = st.session_state.user['role']
        user_name = st.session_state.user.get('name', st.session_state.user['role'])
        
        # Display user info in sidebar
        st.sidebar.markdown("---")
        st.sidebar.info(f"**Logged in as:** {user_name}\n\n**Role:** {user_role}\n\n**Hospital:** {st.session_state.user['hospital']}")
        
        if user_role == 'Admin':
            self.render_admin_interface()
        elif user_role == 'Hospital Staff':
            self.render_staff_interface()
        elif user_role == 'Ambulance Driver':
            self.render_driver_interface()
        
        st.markdown("---")
        st.markdown("**Kisumu County Hospital Referral System** | Secure • Reliable • Efficient")
    
    def render_admin_interface(self):
        st.sidebar.title("Admin Navigation")
        tabs = st.tabs([
            "📊 Dashboard", "📋 Referrals", "🚑 Tracking", "📄 Handovers",
            "💬 Communication", "📈 Reports", "👥 User Management"
        ])
        with tabs[0]:
            self.dashboard_ui.display()
        with tabs[1]:
            self.referral_ui.display()
        with tabs[2]:
            self.tracking_ui.display()
        with tabs[3]:
            self.handover_ui.display()
        with tabs[4]:
            self.communication_ui.display()
        with tabs[5]:
            self.reports_ui.display()
        with tabs[6]:
            self.render_user_management()
    
    def render_staff_interface(self):
        st.sidebar.title("Staff Navigation")
        user_hospital = st.session_state.user['hospital']
        
        if user_hospital == "Kisumu County Referral Hospital":
            # Kisumu County staff can both refer and receive
            tabs = st.tabs([
                "📊 Dashboard", "📋 Create Referral", "🚑 Tracking", "📄 Handovers", "💬 Communication"
            ])
        else:
            # JOOTRH and other hospitals - receive only or refer only
            tabs = st.tabs([
                "📊 Dashboard", "📋 Referrals", "🚑 Tracking", "📄 Handovers", "💬 Communication"
            ])
            
        with tabs[0]:
            self.dashboard_ui.display()
        with tabs[1]:
            self.referral_ui.display()
        with tabs[2]:
            self.tracking_ui.display()
        with tabs[3]:
            self.handover_ui.display()
        with tabs[4]:
            self.communication_ui.display()
    
    def render_driver_interface(self):
        self.driver_ui.display_driver_dashboard()
    
    def render_user_management(self):
        if self.auth.require_auth(['Admin']):
            st.header("👥 User Management")
            col1, col2 = st.columns(2)
            with col1:
                st.subheader("Add New User")
                with st.form("add_user_form"):
                    username = st.text_input("Username")
                    password = st.text_input("Password", type="password")
                    email = st.text_input("Email")
                    role = st.selectbox("Role", ["Admin", "Hospital Staff", "Ambulance Driver"])
                    hospital = st.selectbox("Hospital", ["All Facilities", "Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)", "Kisumu County Referral Hospital"] + hospitals_data['facility_name'][2:])
                    if st.form_submit_button("Add User", use_container_width=True):
                        st.success(f"User {username} added successfully")
            with col2:
                st.subheader("Current Users")
                users_data = [
                    {"Username": "admin", "Role": "Admin", "Hospital": "All Facilities"},
                    {"Username": "hospital_staff", "Role": "Hospital Staff", "Hospital": "JOOTRH"},
                    {"Username": "kisumu_staff", "Role": "Hospital Staff", "Hospital": "Kisumu County Referral Hospital"},
                    {"Username": "driver", "Role": "Ambulance Driver", "Hospital": "Ambulance Service"}
                ]
                st.dataframe(users_data)

# =============================================================================
# RUN APPLICATION
# =============================================================================
if __name__ == "__main__":
    st.set_page_config(
        page_title=Config.PAGE_TITLE,
        page_icon=Config.PAGE_ICON,
        layout=Config.LAYOUT,
        initial_sidebar_state="expanded"
    )
    
    # Custom CSS for better styling
    st.markdown("""
    <style>
    .main-header {
        font-size: 2.5rem;
        color: #1f77b4;
        text-align: center;
        margin-bottom: 2rem;
    }
    .metric-card {
        background-color: #f0f2f6;
        padding: 1rem;
        border-radius: 10px;
        border-left: 5px solid #1f77b4;
    }
    .stButton button {
        width: 100%;
    }
    </style>
    """, unsafe_allow_html=True)
    
    app = HospitalReferralApp()
    app.run()