// Smooth scroll animation
document.addEventListener('DOMContentLoaded', function() {
    // 이메일 복사 기능
    const copyEmailBtn = document.getElementById('copyEmailBtn');
    const emailNote = document.getElementById('emailNote');

    if (copyEmailBtn) {
        copyEmailBtn.addEventListener('click', function() {
            const email = this.getAttribute('data-email');
            
            // 클립보드에 복사
            navigator.clipboard.writeText(email).then(function() {
                // 성공
                copyEmailBtn.classList.add('copied');
                copyEmailBtn.textContent = '✓ 복사됨!';
                emailNote.textContent = '이메일 주소가 클립보드에 복사되었습니다';
                emailNote.style.color = '#22c55e';
                
                // 2초 후 원래대로
                setTimeout(() => {
                    copyEmailBtn.classList.remove('copied');
                    copyEmailBtn.textContent = email;
                    emailNote.textContent = '클릭하면 이메일 주소가 복사됩니다';
                    emailNote.style.color = '';
                }, 2000);
            }).catch(function(err) {
                // 실패 (구형 브라우저)
                alert('이메일 주소: ' + email);
            });
        });
    }

    // Add animation on scroll
    const observerOptions = {
        threshold: 0.1,
        rootMargin: '0px 0px -50px 0px'
    };

    const observer = new IntersectionObserver(function(entries) {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.style.opacity = '1';
                entry.target.style.transform = 'translateY(0)';
            }
        });
    }, observerOptions);

    // Observe all feature cards and steps
    const animatedElements = document.querySelectorAll('.feature-card, .step, .command-group, .email-card');
    animatedElements.forEach(el => {
        el.style.opacity = '0';
        el.style.transform = 'translateY(20px)';
        el.style.transition = 'all 0.6s ease-out';
        observer.observe(el);
    });

    // Add hover effect to CTA button
    const ctaButtons = document.querySelectorAll('.cta-button');
    ctaButtons.forEach(button => {
        button.addEventListener('mouseenter', function() {
            this.style.transform = 'scale(1.05) translateY(-3px)';
        });
        
        button.addEventListener('mouseleave', function() {
            this.style.transform = 'scale(1) translateY(0)';
        });
    });

    // Parallax effect for hero background
    window.addEventListener('scroll', function() {
        const scrolled = window.pageYOffset;
        const heroBg = document.querySelector('.hero-bg');
        if (heroBg) {
            heroBg.style.transform = `translateY(${scrolled * 0.5}px)`;
        }
    });

    // Add click tracking for CTA buttons (optional - for analytics)
    ctaButtons.forEach(button => {
        button.addEventListener('click', function(e) {
            console.log('CTA Button clicked:', this.href);
            // Add your analytics tracking here if needed
        });
    });
});

// Add floating animation to feature icons
document.addEventListener('DOMContentLoaded', function() {
    const featureIcons = document.querySelectorAll('.feature-icon');
    
    featureIcons.forEach((icon, index) => {
        // Stagger the animation delay
        icon.style.animation = `float 3s ease-in-out ${index * 0.2}s infinite`;
    });
});

// Add keyframes for float animation dynamically
const style = document.createElement('style');
style.textContent = `
    @keyframes float {
        0%, 100% {
            transform: translateY(0px);
        }
        50% {
            transform: translateY(-10px);
        }
    }
`;
document.head.appendChild(style);

