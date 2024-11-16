from typing import Optional

from sqlalchemy.orm import Session
from app.crud.base import CRUDBase
from app.models.webhook import Webhook
from app.schemas.webhook import WebhookCreate, WebhookUpdate
from typing import Any, Dict, Optional, Union

class CRUDWebhook(CRUDBase[Webhook, WebhookCreate, WebhookUpdate]):
    def get(self, db: Session, id: int) -> Optional[Webhook]:
        return db.query(self.model).filter(self.model.id == id).first()
    
    def get_by_order(self, db: Session, order_id: str, event: str) -> Optional[Webhook]:
        return db.query(self.model).filter(self.model.order_id == order_id, self.model.event == event).first()
    
    def create(self, db: Session, *, obj_in: WebhookCreate) -> Webhook:
        db_obj = Webhook(
            order_id=obj_in.order_id,
            endpoint=obj_in.endpoint,
            event=obj_in.event,
            payload=obj_in.payload,
            retries=obj_in.retries,
            delay=obj_in.delay,
        )
        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        return db_obj
    
    # def update(
    #     self, db: Session, *, db_obj: Webhook, obj_in: Union[WebhookUpdate, Dict[str, Any]]
    # ) -> Webhook:
    #     if isinstance(obj_in, dict):
    #         update_data = obj_in
    #     else:
    #         update_data = obj_in.dict(exclude_unset=True)
        
    #     return super().update(db, db_obj=db_obj, obj_in=update_data)

webhook = CRUDWebhook(Webhook)
