import os
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, HTTPException
from typing import Dict, Any

from app.config import settings
from app.database import get_db_connection
from app.models import SettingsImportPreviewRequest, SettingsImportRequest

router = APIRouter(prefix="/settings", tags=["settings"])

def export_settings() -> dict:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        
        # Export Model Settings
        cur.execute("SELECT role, model_name FROM model_settings")
        model_settings = [{"role": row["role"], "model_name": row["model_name"]} for row in cur.fetchall()]
        
        # Export Knowledge Bases (without document link lists)
        cur.execute("SELECT name, description FROM knowledge_bases")
        knowledge_bases = [{"name": row["name"], "description": row["description"]} for row in cur.fetchall()]
        
        # Export Prompt Templates
        cur.execute("SELECT name, description, category, template, variables_json, tags_json FROM prompt_templates")
        prompt_templates = [dict(row) for row in cur.fetchall()]
        
        return {
            "app": "local-ai-coding-assistant",
            "version": 1,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "data": {
                "model_settings": model_settings,
                "knowledge_bases": knowledge_bases,
                "prompt_templates": prompt_templates,
                "preferences": {} # Placeholder for future settings
            }
        }
    finally:
        conn.close()

def backup_current_settings() -> str:
    db_path = Path(settings.app_database_path)
    backup_dir = db_path.parent / "settings_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    
    current_export = export_settings()
    backup_id = f"settings_backup_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.json"
    backup_path = backup_dir / backup_id
    
    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump(current_export, f, indent=2)
        
    return str(backup_path)

def validate_import_payload(payload: dict) -> dict:
    warnings = []
    
    if payload.get("app") != "local-ai-coding-assistant":
        raise ValueError("Invalid export format: app name mismatch.")
        
    data = payload.get("data", {})
    
    models_count = len(data.get("model_settings", []))
    kbs_count = len(data.get("knowledge_bases", []))
    prompts_count = len(data.get("prompt_templates", []))
    
    return {
        "valid": True,
        "summary": {
            "model_settings": models_count,
            "knowledge_bases": kbs_count,
            "prompt_templates": prompts_count
        },
        "warnings": warnings
    }

def import_settings(payload: dict, overwrite: bool = False) -> dict:
    data = payload.get("data", {})
    
    created = {"model_settings": 0, "knowledge_bases": 0, "prompt_templates": 0}
    updated = {"model_settings": 0, "knowledge_bases": 0, "prompt_templates": 0}
    skipped = {"model_settings": 0, "knowledge_bases": 0, "prompt_templates": 0}
    
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db_connection()
    try:
        # Import Model Settings
        for item in data.get("model_settings", []):
            role = item.get("role")
            model_name = item.get("model_name")
            if not role or not model_name:
                continue
                
            cur = conn.cursor()
            cur.execute("SELECT id FROM model_settings WHERE role = ?", (role,))
            existing = cur.fetchone()
            
            if existing:
                if overwrite:
                    conn.execute("UPDATE model_settings SET model_name = ?, updated_at = ? WHERE role = ?", (model_name, now, role))
                    updated["model_settings"] += 1
                else:
                    skipped["model_settings"] += 1
            else:
                conn.execute("INSERT INTO model_settings (id, role, model_name, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                             (str(uuid.uuid4()), role, model_name, now, now))
                created["model_settings"] += 1

        # Import Knowledge Bases
        for item in data.get("knowledge_bases", []):
            name = item.get("name")
            description = item.get("description")
            if not name:
                continue
                
            cur = conn.cursor()
            cur.execute("SELECT id FROM knowledge_bases WHERE name = ?", (name,))
            existing = cur.fetchone()
            
            if existing:
                if overwrite:
                    conn.execute("UPDATE knowledge_bases SET description = ?, updated_at = ? WHERE name = ?", (description, now, name))
                    updated["knowledge_bases"] += 1
                else:
                    skipped["knowledge_bases"] += 1
            else:
                conn.execute("INSERT INTO knowledge_bases (id, name, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                             (str(uuid.uuid4()), name, description, now, now))
                created["knowledge_bases"] += 1

        # Import Prompt Templates
        for item in data.get("prompt_templates", []):
            name = item.get("name")
            category = item.get("category")
            template = item.get("template")
            if not name or not category or not template:
                continue
                
            cur = conn.cursor()
            cur.execute("SELECT id FROM prompt_templates WHERE name = ? AND category = ?", (name, category))
            existing = cur.fetchone()
            
            if existing:
                if overwrite:
                    conn.execute("""
                        UPDATE prompt_templates 
                        SET description = ?, template = ?, variables_json = ?, tags_json = ?, updated_at = ? 
                        WHERE name = ? AND category = ?
                    """, (item.get("description"), template, item.get("variables_json"), item.get("tags_json"), now, name, category))
                    updated["prompt_templates"] += 1
                else:
                    skipped["prompt_templates"] += 1
            else:
                conn.execute("""
                    INSERT INTO prompt_templates (id, name, description, category, template, variables_json, tags_json, created_at, updated_at) 
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (str(uuid.uuid4()), name, item.get("description"), category, template, item.get("variables_json"), item.get("tags_json"), now, now))
                created["prompt_templates"] += 1

        conn.commit()
    finally:
        conn.close()
        
    return {"created": created, "updated": updated, "skipped": skipped}

@router.get("/export")
def handle_export():
    try:
        data = export_settings()
        return {
            "status": "ok",
            "export": data
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/import/preview")
def handle_import_preview(req: SettingsImportPreviewRequest):
    try:
        result = validate_import_payload(req.export)
        return {
            "status": "ok",
            "valid": result["valid"],
            "summary": result["summary"],
            "warnings": result["warnings"]
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/import")
def handle_import(req: SettingsImportRequest):
    if not req.confirm:
        raise HTTPException(status_code=400, detail="confirm=true is required to import settings.")
        
    try:
        # Validate first
        validate_import_payload(req.export)
        
        # Backup
        backup_path = backup_current_settings()
        
        # Import
        result = import_settings(req.export, req.overwrite)
        
        return {
            "status": "imported",
            "backup_id": backup_path,
            "created": result["created"],
            "updated": result["updated"],
            "skipped": result["skipped"],
            "warnings": []
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
