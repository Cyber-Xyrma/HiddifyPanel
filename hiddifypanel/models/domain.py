from enum import auto
from urllib.parse import urlparse

from flask import flash, request
from sqlalchemy_serializer import SerializerMixin
from strenum import StrEnum

from hiddifypanel.panel.database import db
from hiddifypanel import hutils
from .config import hconfig
from .config_enum import ConfigEnum
from sqlalchemy.orm import backref
from flask_babelex import lazy_gettext as _


class DomainType(StrEnum):
    direct = auto()
    sub_link_only = auto()
    cdn = auto()
    auto_cdn_ip = auto()
    relay = auto()
    reality = auto()
    old_xtls_direct = auto()
    worker = auto()
    fake = auto()

    # fake_cdn = "fake_cdn"
    # telegram_faketls = "telegram_faketls"
    # ss_faketls = "ss_faketls"


ShowDomain = db.Table('show_domain',
                      db.Column('domain_id', db.Integer, db.ForeignKey('domain.id'), primary_key=True),
                      db.Column('related_id', db.Integer, db.ForeignKey('domain.id'), primary_key=True)
                      )


class Domain(db.Model, SerializerMixin):
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    child_id = db.Column(db.Integer, db.ForeignKey('child.id'), default=0)
    domain = db.Column(db.String(200), nullable=False, unique=False)
    alias = db.Column(db.String(200))
    sub_link_only = db.Column(db.Boolean, nullable=False, default=False)
    mode = db.Column(db.Enum(DomainType), nullable=False, default=DomainType.direct)
    cdn_ip = db.Column(db.Text(2000), nullable=True, default='')
    # port_index=db.Column(db.Integer, nullable=True, default=0)
    grpc = db.Column(db.Boolean, nullable=True, default=False)
    servernames = db.Column(db.String(1000), nullable=True, default='')
    # show_all=db.Column(db.Boolean, nullable=True)
    show_domains = db.relationship('Domain', secondary=ShowDomain,
                                   primaryjoin=id == ShowDomain.c.domain_id,
                                   secondaryjoin=id == ShowDomain.c.related_id,
                                   backref=backref('showed_by_domains', lazy='dynamic')
                                   )

    def __repr__(self):
        return f'{self.domain}'

    def to_dict(self, dump_ports=False):
        data = {
            'domain': self.domain.lower(),
            'mode': self.mode,
            'alias': self.alias,
            # 'sub_link_only':d.sub_link_only,
            'child_unique_id': self.child.unique_id if self.child else '',
            'cdn_ip': self.cdn_ip,
            'servernames': self.servernames,
            'grpc': self.grpc,
            'show_domains': [dd.domain for dd in self.show_domains],
        }

        if dump_ports:
            data["internal_port_hysteria2"] = self.internal_port_hysteria2
            data["internal_port_tuic"] = self.internal_port_tuic
            data["internal_port_reality"] = self.internal_port_reality
            data["need_valid_ssl"] = self.need_valid_ssl

        return data

    @property
    def need_valid_ssl(self):
        return self.mode in [DomainType.direct, DomainType.cdn, DomainType.worker, DomainType.relay, DomainType.auto_cdn_ip, DomainType.old_xtls_direct, DomainType.sub_link_only]

    @property
    def port_index(self):
        return self.id

    @property
    def internal_port_hysteria2(self):
        if self.mode not in [DomainType.direct, DomainType.relay, DomainType.fake]:
            return 0
        return int(hconfig(ConfigEnum.hysteria_port))+self.port_index

    @property
    def internal_port_tuic(self):
        if self.mode not in [DomainType.direct, DomainType.relay, DomainType.fake]:
            return 0
        return int(hconfig(ConfigEnum.tuic_port))+self.port_index

    @property
    def internal_port_reality(self):
        if self.mode != DomainType.reality:
            return 0
        return int(hconfig(ConfigEnum.reality_port))+self.port_index


def hdomains(mode):
    domains = Domain.query.filter(Domain.mode == mode).all()
    if domains:
        return [d.domain for d in domains]
    return []


def hdomain(mode):
    domains = hdomains(mode)
    if domains:
        return domains[0]
    return None


def get_hdomains():
    return {mode: hdomains(mode) for mode in DomainType}


def get_domain(domain):
    return Domain.query.filter(Domain.domain == domain).first()


def get_panel_domains(always_add_ip=False, always_add_all_domains=False):
    domains = []
    if hconfig(ConfigEnum.is_parent):
        from .parent_domain import ParentDomain
        domains = ParentDomain.query.all()
    else:
        domains = Domain.query.filter(Domain.mode == DomainType.sub_link_only).all()
        if not len(domains) or always_add_all_domains:
            domains = Domain.query.filter(Domain.mode.notin_([DomainType.fake, DomainType.reality])).all()

    if len(domains) == 0 and request:
        domains = [Domain(domain=request.host)]
    if len(domains) == 0 or always_add_ip:
        from hiddifypanel.panel import hiddify
        domains += [Domain(domain=hutils.ip.get_ip(4))]
    return domains


def get_proxy_domains(domain):
    if hconfig(ConfigEnum.is_parent):
        from hiddifypanel.models.parent_domain import ParentDomain
        db_domain = ParentDomain.query.filter(ParentDomain.domain == domain).first() or ParentDomain(domain=domain, show_domains=[])
    else:
        db_domain = Domain.query.filter(Domain.domain == domain).first() or Domain(domain=domain, mode=DomainType.direct, cdn_ip='', show_domains=[])
    return get_proxy_domains_db(db_domain)


def get_proxy_domains_db(db_domain):
    if not db_domain:
        domain = urlparse(request.base_url).hostname
        db_domain = Domain(domain=domain, mode=DomainType.direct, show_domains=[])
        # print("no domain")
        flash(_("This domain does not exist in the panel!" + domain))

    return db_domain.show_domains or Domain.query.all()


def get_current_proxy_domains(force_domain=None):
    domain = force_domain or urlparse(request.base_url).hostname
    return get_proxy_domains(domain)


def add_or_update_domain(commit=True, child_id=0, **domain):
    dbdomain = Domain.query.filter(Domain.domain == domain['domain']).first()
    if not dbdomain:
        dbdomain = Domain(domain=domain['domain'])
        db.session.add(dbdomain)
    dbdomain.child_id = child_id

    dbdomain.mode = domain['mode']
    if (str(domain.get('sub_link_only', False)).lower() == 'true'):
        dbdomain.mode = DomainType.sub_link_only
    dbdomain.cdn_ip = domain.get('cdn_ip', '')
    dbdomain.alias = domain.get('alias', '')
    dbdomain.grpc = domain.get('grpc', False)
    dbdomain.servernames = domain.get('servernames', '')
    show_domains = domain.get('show_domains', [])
    dbdomain.show_domains = Domain.query.filter(Domain.domain.in_(show_domains)).all()
    if commit:
        db.session.commit()


def bulk_register_domains(domains, commit=True, remove=False, override_child_id=None):
    from hiddifypanel.panel import hiddify
    child_ids = {}
    for domain in domains:
        child_id = override_child_id if override_child_id is not None else hiddify.get_child(domain.get('child_unique_id', None))
        child_ids[child_id] = 1
        add_or_update_domain(commit=False, child_id=child_id, **domain)
    if remove and len(child_ids):
        dd = {d['domain']: 1 for d in domains}
        for d in Domain.query.filter(Domain.child_id.in_(child_ids)):
            if d.domain not in dd:
                db.session.delete(d)

    # if commit:
    db.session.commit()
    for domain in domains:
        child_id = override_child_id if override_child_id is not None else hiddify.get_child(domain.get('child_unique_id', None))
        add_or_update_domain(commit=False, child_id=child_id, **domain)
    if commit:
        db.session.commit()
