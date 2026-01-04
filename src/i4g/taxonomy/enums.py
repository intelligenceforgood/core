"""
Fraud Taxonomy Enums
Version: fraud-taxonomy.v1.0

Auto-generated from definitions.yaml. DO NOT EDIT.
"""

from enum import Enum

class ScamIntent(str, Enum):
    # Pretending to be a trusted entity
    IMPOSTER = "INTENT.IMPOSTER"
    # Promises of financial returns
    INVESTMENT = "INTENT.INVESTMENT"
    # Emotional relationship for fraud
    ROMANCE = "INTENT.ROMANCE"
    # Fake job or task-based fraud
    EMPLOYMENT = "INTENT.EMPLOYMENT"
    # Fake goods or sellers
    SHOPPING = "INTENT.SHOPPING"
    # Fake tech assistance
    TECH_SUPPORT = "INTENT.TECH_SUPPORT"
    # Fake winnings
    PRIZE = "INTENT.PRIZE"
    # Threat-based coercion
    EXTORTION = "INTENT.EXTORTION"
    # Fake disaster or cause appeals
    CHARITY = "INTENT.CHARITY"

class DeliveryChannel(str, Enum):
    # Communication via email
    EMAIL = "CHANNEL.EMAIL"
    # Text messages or SMS
    SMS = "CHANNEL.SMS"
    # WhatsApp, Telegram, Signal, etc.
    CHAT = "CHANNEL.CHAT"
    # Facebook, Instagram, Twitter, LinkedIn, etc.
    SOCIAL = "CHANNEL.SOCIAL"
    # Voice calls
    PHONE = "CHANNEL.PHONE"
    # Malicious websites or landing pages
    WEB = "CHANNEL.WEB"

class SocialEngineeringTechnique(str, Enum):
    # Time pressure, deadlines
    URGENCY = "SE.URGENCY"
    # Government, bank, employer tone
    AUTHORITY = "SE.AUTHORITY"
    # Limited availability
    SCARCITY = "SE.SCARCITY"
    # Threats, loss, legal trouble
    FEAR = "SE.FEAR"
    # Gifts, favors
    RECIPROCITY = "SE.RECIPROCITY"
    # Long-term rapport
    TRUST_BUILDING = "SE.TRUST_BUILDING"
    # Overwhelming steps
    CONFUSION = "SE.CONFUSION"

class RequestedAction(str, Enum):
    # Direct money transfer
    SEND_MONEY = "ACTION.SEND_MONEY"
    # Purchase and share gift card codes
    GIFT_CARDS = "ACTION.GIFT_CARDS"
    # Send crypto to a wallet address
    CRYPTO = "ACTION.CRYPTO"
    # Provide login details or passwords
    CREDENTIALS = "ACTION.CREDENTIALS"
    # Download and install apps or remote access tools
    INSTALL = "ACTION.INSTALL"
    # Visit a specific URL
    CLICK_LINK = "ACTION.CLICK_LINK"
    # Share SSN, ID, or other sensitive info
    PROVIDE_PII = "ACTION.PROVIDE_PII"

class ClaimedPersona(str, Enum):
    # IRS, FBI, Police, etc.
    GOVERNMENT = "PERSONA.GOVERNMENT"
    # Chase, Wells Fargo, PayPal, etc.
    BANK = "PERSONA.BANK"
    # Microsoft, Apple, Amazon support
    TECH = "PERSONA.TECH"
    # Recruiter, Boss, CEO
    EMPLOYER = "PERSONA.EMPLOYER"
    # Boyfriend, Girlfriend, Match
    ROMANTIC = "PERSONA.ROMANTIC"
    # Facebook Marketplace, Craigslist user
    MARKETPLACE = "PERSONA.MARKETPLACE"
    # Red Cross, GoFundMe, etc.
    CHARITY = "PERSONA.CHARITY"
