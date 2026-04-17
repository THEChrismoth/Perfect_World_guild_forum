from django import forms
from .models import AuctionBid, AuctionLot

class BidForm(forms.ModelForm):
    class Meta:
        model = AuctionBid
        fields = ['bid_amount']
        widgets = {
            'bid_amount': forms.NumberInput(attrs={
                'class': 'bid-input',
                'placeholder': 'Ваша ставка'
            })
        }
    
    def __init__(self, *args, **kwargs):
        self.lot = kwargs.pop('lot', None)
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        if self.lot:
            min_bid = self.lot.current_price + self.lot.min_step
            self.fields['bid_amount'].label = f'Ваша ставка (мин. {min_bid})'
            self.fields['bid_amount'].widget.attrs['min'] = min_bid
            self.fields['bid_amount'].widget.attrs['step'] = self.lot.min_step
    
    def clean_bid_amount(self):
        bid_amount = self.cleaned_data['bid_amount']
        
        if not self.lot.is_active:
            raise forms.ValidationError('Аукцион уже завершен')
        
        min_bid = self.lot.current_price + self.lot.min_step
        if bid_amount < min_bid:
            raise forms.ValidationError(f'Минимальная ставка: {min_bid}')
        
        # Проверка, что пользователь не делает ставку сам на себя
        last_bid = self.lot.bids.filter(status='active').first()
        if last_bid and last_bid.bidder == self.user:
            raise forms.ValidationError('Вы не можете делать ставки подряд')
        
        # Проверка, не делал ли пользователь уже ставку
        existing_bid = self.lot.bids.filter(bidder=self.user, status__in=['active', 'frozen']).first()
        if existing_bid:
            raise forms.ValidationError('Вы уже сделали ставку на этот лот')
        
        # Проверка наличия достаточного количества доступных очков
        available_points = self.user.profile.get_available_points()
        if available_points < bid_amount:
            raise forms.ValidationError(
                f'Недостаточно доступных очков. Доступно: {available_points} ⭐ '
                f'(Всего: {self.user.profile.activity_points} ⭐)'
            )
        
        return bid_amount
